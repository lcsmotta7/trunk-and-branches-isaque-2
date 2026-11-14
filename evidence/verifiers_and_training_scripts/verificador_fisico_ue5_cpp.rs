// Verificador Físico Determinístico UE5 C++20 + Tree-Sitter AST (`Zero Achismo` — Seção 4.2 & 3)
// - Parseia `.h` e `.cpp` via `tree-sitter-cpp` (AST real)
// - Valida as 8 invariantes obrigatórias do Unreal Header Tool (UHT) e GC de UObject
// - Executa compilação sintática/semântica real C++20 via `clang++.exe -fsyntax-only -std=c++20`
// - Também expõe `--extract-ast` (`cpp` / `python`) via `tree-sitter` para a faceta `V_ast` da `arena-kev-triplo.mmap`

use regex::Regex;
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeSet,
    env, fs,
    path::{Path, PathBuf},
    process::Command,
};
use tree_sitter::{Node, Parser};

const DEFAULT_CLANG_WIN: &str =
    r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\Llvm\x64\bin\clang++.exe";

#[derive(Debug, Clone)]
struct ReflectedTypeInfo {
    kind_macro: String, // UCLASS or USTRUCT
    type_name: String,
    base_name: Option<String>,
    generated_body_line_1based: Option<usize>,
}

#[derive(Debug, Serialize)]
struct Ue5VerifyReceipt {
    schema: &'static str,
    header_path: String,
    source_path: String,
    aprovado_mecanico: bool,
    invariantes_8_de_8: InvariantesUht,
    violacoes: Vec<String>,
    ast_telemetria: AstTelemetria,
    clang_cpp20: ClangResult,
}

#[derive(Debug, Serialize)]
struct InvariantesUht {
    inv_01_pragma_once: bool,
    inv_02_generated_h_ultimo_include: bool,
    inv_03_uclass_ou_ustruct_presente: bool,
    inv_04_generated_body_pareado: bool,
    inv_05_zero_ponteiro_uobject_cru_sem_gc: bool,
    inv_06_zero_new_bruto_em_uobject: bool,
    inv_07_ciclo_vida_e_macros_ue5_validos: bool,
    inv_08_clang_cpp20_fsyntax_only_zero_erros: bool,
}

#[derive(Debug, Serialize)]
struct AstTelemetria {
    header_ast_errors: usize,
    source_ast_errors: usize,
    includes_header_ordem: Vec<String>,
    tipos_refletidos: Vec<String>,
    membros_uobject_auditados: usize,
    ponteiros_crus_uobject_violadores: Vec<String>,
    new_bruto_uobject_violadores: Vec<String>,
    ufunctions_detectadas: usize,
    uproperties_detectadas: usize,
}

#[derive(Debug, Serialize)]
struct ClangResult {
    binario: String,
    exit_code: i32,
    zero_erros_sintaxe: bool,
    stderr_diagnostico: String,
}

fn node_text<'a>(node: Node<'_>, src: &'a [u8]) -> &'a str {
    std::str::from_utf8(&src[node.start_byte()..node.end_byte()]).unwrap_or("")
}

fn count_ast_errors(node: Node<'_>) -> usize {
    let mut err = usize::from(node.is_error() || node.is_missing());
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        err += count_ast_errors(child);
    }
    err
}

fn is_unreal_uobject_type(type_ident: &str) -> bool {
    let t = type_ident.trim();
    if t.len() < 2 {
        return false;
    }
    let bytes = t.as_bytes();
    let starts_ua = bytes[0] == b'U' || bytes[0] == b'A';
    let second_upper = bytes[1].is_ascii_uppercase();
    starts_ua && second_upper && t.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_')
}

fn collect_includes(root: Node<'_>, src: &[u8]) -> Vec<String> {
    let mut out = Vec::new();
    fn walk(n: Node<'_>, src: &[u8], out: &mut Vec<String>) {
        if n.kind() == "preproc_include" {
            if let Some(p) = n.child_by_field_name("path") {
                let raw = node_text(p, src).trim().trim_matches(|c| c == '"' || c == '<' || c == '>');
                out.push(raw.to_owned());
            } else {
                let txt = node_text(n, src);
                if let Some(rest) = txt.strip_prefix("#include") {
                    out.push(rest.trim().trim_matches(|c| c == '"' || c == '<' || c == '>').to_owned());
                }
            }
        }
        let mut c = n.walk();
        for ch in n.children(&mut c) {
            walk(ch, src, out);
        }
    }
    walk(root, src, &mut out);
    out
}

fn has_pragma_once(root: Node<'_>, src: &[u8]) -> bool {
    fn walk(n: Node<'_>, src: &[u8]) -> bool {
        if n.kind().starts_with("preproc") {
            let t = node_text(n, src);
            if t.lines().any(|l| {
                let s = l.trim();
                s.starts_with("#pragma") && s.contains("once")
            }) {
                return true;
            }
        }
        let mut c = n.walk();
        for ch in n.children(&mut c) {
            if walk(ch, src) {
                return true;
            }
        }
        false
    }
    walk(root, src)
}

fn has_pointer_declarator(n: Node<'_>) -> bool {
    if n.kind() == "pointer_declarator" || n.kind() == "abstract_pointer_declarator" {
        return true;
    }
    let mut c = n.walk();
    for ch in n.children(&mut c) {
        if has_pointer_declarator(ch) {
            return true;
        }
    }
    false
}

fn audit_uobject_fields_and_new(
    root: Node<'_>,
    src: &[u8],
    lines: &[&str],
    membros_auditados: &mut usize,
    raw_ptr_violacoes: &mut Vec<String>,
    new_violacoes: &mut Vec<String>,
) {
    let re_tobj = Regex::new(r"\bTObjectPtr\s*<\s*([A-Za-z_][A-Za-z0-9_]*)\s*>").unwrap();
    let re_weak = Regex::new(r"\b(?:TWeakObjectPtr|TSoftObjectPtr|TSubclassOf)\s*<\s*([A-Za-z_][A-Za-z0-9_]*)\s*>").unwrap();

    fn walk(
        n: Node<'_>,
        src: &[u8],
        lines: &[&str],
        re_tobj: &Regex,
        re_weak: &Regex,
        membros_auditados: &mut usize,
        raw_ptr_violacoes: &mut Vec<String>,
        new_violacoes: &mut Vec<String>,
    ) {
        if n.kind() == "field_declaration" {
            let txt = node_text(n, src).trim();
            let line_idx = n.start_position().row;
            // Verificar janela de até 4 linhas acima dentro do mesmo bloco para UPROPERTY(...)
            let start_look = line_idx.saturating_sub(4);
            let window_above = lines[start_look..=line_idx].join("\n");
            let has_uproperty = window_above.contains("UPROPERTY(");

            if let Some(cap) = re_tobj.captures(txt) {
                let inner_ty = cap.get(1).map(|m| m.as_str()).unwrap_or("");
                if is_unreal_uobject_type(inner_ty) {
                    *membros_auditados += 1;
                    if !has_uproperty {
                        raw_ptr_violacoes.push(format!(
                            "L{}: TObjectPtr<{}> sem UPROPERTY(...) para rastreio do GC: `{}`",
                            line_idx + 1,
                            inner_ty,
                            txt
                        ));
                    }
                }
            } else if re_weak.is_match(txt) {
                *membros_auditados += 1;
            } else if has_pointer_declarator(n) {
                if let Some(ty_node) = n.child_by_field_name("type") {
                    let ty_txt = node_text(ty_node, src)
                        .trim()
                        .trim_start_matches("const ")
                        .trim_start_matches("class ")
                        .trim_start_matches("struct ")
                        .trim();
                    if is_unreal_uobject_type(ty_txt) {
                        *membros_auditados += 1;
                        if !has_uproperty {
                            raw_ptr_violacoes.push(format!(
                                "L{}: Ponteiro cru `{}` sem UPROPERTY/TWeakObjectPtr (dangling pointer fatal sob GC): `{}`",
                                line_idx + 1,
                                ty_txt,
                                txt
                            ));
                        }
                    }
                }
            }
        } else if n.kind() == "new_expression" {
            let txt = node_text(n, src).trim();
            let line_idx = n.start_position().row;
            if let Some(ty_node) = n.child_by_field_name("type") {
                let ty_txt = node_text(ty_node, src).trim();
                let base_ident = ty_txt.split('<').next().unwrap_or(ty_txt).trim();
                if is_unreal_uobject_type(base_ident) {
                    new_violacoes.push(format!(
                        "L{}: `new` bruto proibido em classe UObject `{}` (use CreateDefaultSubobject ou NewObject): `{}`",
                        line_idx + 1,
                        base_ident,
                        txt
                    ));
                }
            }
        }

        let mut c = n.walk();
        for ch in n.children(&mut c) {
            walk(
                ch,
                src,
                lines,
                re_tobj,
                re_weak,
                membros_auditados,
                raw_ptr_violacoes,
                new_violacoes,
            );
        }
    }

    walk(
        root,
        src,
        lines,
        &re_tobj,
        &re_weak,
        membros_auditados,
        raw_ptr_violacoes,
        new_violacoes,
    );
}

fn scan_reflected_types(h_text: &str) -> Vec<ReflectedTypeInfo> {
    let lines: Vec<&str> = h_text.lines().collect();
    let re_macro = Regex::new(r"^\s*(UCLASS|USTRUCT)\s*\(").unwrap();
    let re_decl = Regex::new(
        r"^\s*(?:class|struct)\s+(?:[A-Z0-9_]+_API\s+)?([A-Za-z_][A-Za-z0-9_]*)(?:\s+final)?(?:\s*:\s*public\s+([A-Za-z_][A-Za-z0-9_]*))?",
    )
    .unwrap();
    let re_gen_body = Regex::new(r"\bGENERATED_BODY\s*\(\s*\)").unwrap();

    let mut out = Vec::new();
    let mut i = 0;
    while i < lines.len() {
        if let Some(cap_m) = re_macro.captures(lines[i]) {
            let kind_macro = cap_m.get(1).unwrap().as_str().to_owned();
            // Procurar declaração class/struct nas próximas 6 linhas
            let mut j = i + 1;
            let mut found_decl = None;
            while j < lines.len() && j <= i + 6 {
                if let Some(cap_d) = re_decl.captures(lines[j]) {
                    let tname = cap_d.get(1).unwrap().as_str().to_owned();
                    let bname = cap_d.get(2).map(|m| m.as_str().to_owned());
                    found_decl = Some((j, tname, bname));
                    break;
                }
                j += 1;
            }
            if let Some((decl_idx, type_name, base_name)) = found_decl {
                // Procurar GENERATED_BODY() dentro do escopo desta classe/struct
                let mut brace_depth: i32 = 0;
                let mut seen_open = false;
                let mut gen_line = None;
                for (k, ln) in lines.iter().enumerate().skip(decl_idx) {
                    if re_gen_body.is_match(ln) && gen_line.is_none() {
                        gen_line = Some(k + 1); // 1-based line number for __LINE__
                    }
                    for ch in ln.chars() {
                        if ch == '{' {
                            brace_depth += 1;
                            seen_open = true;
                        } else if ch == '}' {
                            brace_depth -= 1;
                        }
                    }
                    if seen_open && brace_depth <= 0 {
                        i = k;
                        break;
                    }
                }
                out.push(ReflectedTypeInfo {
                    kind_macro,
                    type_name,
                    base_name,
                    generated_body_line_1based: gen_line,
                });
            }
        }
        i += 1;
    }
    out
}

fn build_ue5_coreminimal_stub() -> &'static str {
    r#"#pragma once
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <algorithm>
#include <functional>
#include <initializer_list>
#include <map>
#include <memory>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

using int8 = std::int8_t;
using int16 = std::int16_t;
using int32 = std::int32_t;
using int64 = std::int64_t;
using uint8 = std::uint8_t;
using uint16 = std::uint16_t;
using uint32 = std::uint32_t;
using uint64 = std::uint64_t;

#ifndef TEXT
#define TEXT(x) x
#endif

#define UCLASS(...)
#define USTRUCT(...)
#define UENUM(...)
#define UMETA(...)
#define UPROPERTY(...)
#define UFUNCTION(...)

#define UE_BODY_CONCAT_INNER(A, B, C, D) A##B##C##D
#define UE_BODY_CONCAT(A, B, C, D) UE_BODY_CONCAT_INNER(A, B, C, D)
#ifndef CURRENT_FILE_ID
#define CURRENT_FILE_ID FID_Default
#endif
#define GENERATED_BODY(...) UE_BODY_CONCAT(CURRENT_FILE_ID, _, __LINE__, _GENERATED_BODY)

enum ENameNone { NAME_None = 0 };
inline constexpr int32 INDEX_NONE = -1;
inline constexpr float KINDA_SMALL_NUMBER = 1.e-4f;
inline constexpr float SMALL_NUMBER = 1.e-8f;

class FString {
    std::string Data;
public:
    FString() = default;
    FString(const char* S) : Data(S ? S : "") {}
    FString(const std::string& S) : Data(S) {}
    bool IsEmpty() const { return Data.empty(); }
    int32 Len() const { return static_cast<int32>(Data.size()); }
    const char* operator*() const { return Data.c_str(); }
    bool operator==(const FString& Other) const { return Data == Other.Data; }
    bool operator!=(const FString& Other) const { return Data != Other.Data; }
    FString operator+(const FString& Other) const { return FString(Data + Other.Data); }
    static FString Printf(const char* Fmt, ...) { return FString(Fmt); }
    static FString FromInt(int32 V) { return FString(std::to_string(V)); }
    static FString SanitizeFloat(double V) { return FString(std::to_string(V)); }
};

class FName {
    std::string Name;
public:
    FName() = default;
    FName(ENameNone) : Name("") {}
    FName(const char* S) : Name(S ? S : "") {}
    FName(const FString& S) : Name(*S) {}
    bool IsNone() const { return Name.empty(); }
    FString ToString() const { return FString(Name); }
    bool operator==(const FName& Other) const { return Name == Other.Name; }
    bool operator!=(const FName& Other) const { return Name != Other.Name; }
    bool operator==(ENameNone) const { return Name.empty(); }
    bool operator!=(ENameNone) const { return !Name.empty(); }
    bool operator<(const FName& Other) const { return Name < Other.Name; }
};

class FText {
    FString Str;
public:
    FText() = default;
    static FText FromString(const FString& S) { FText T; T.Str = S; return T; }
    static FText FromName(const FName& N) { return FromString(N.ToString()); }
    static FText GetEmpty() { return FText(); }
    FString ToString() const { return Str; }
    bool IsEmpty() const { return Str.IsEmpty(); }
};

struct FVector {
    double X = 0.0;
    double Y = 0.0;
    double Z = 0.0;
    constexpr FVector() = default;
    constexpr explicit FVector(double InF) : X(InF), Y(InF), Z(InF) {}
    constexpr FVector(double InX, double InY, double InZ) : X(InX), Y(InY), Z(InZ) {}
    static const FVector ZeroVector;
    static const FVector OneVector;
    static const FVector UpVector;
    static const FVector ForwardVector;
    FVector operator+(const FVector& V) const { return FVector(X + V.X, Y + V.Y, Z + V.Z); }
    FVector operator-(const FVector& V) const { return FVector(X - V.X, Y - V.Y, Z - V.Z); }
    FVector operator*(double Scale) const { return FVector(X * Scale, Y * Scale, Z * Scale); }
    FVector operator/(double Scale) const { return FVector(X / Scale, Y / Scale, Z / Scale); }
    FVector& operator+=(const FVector& V) { X += V.X; Y += V.Y; Z += V.Z; return *this; }
    FVector& operator-=(const FVector& V) { X -= V.X; Y -= V.Y; Z -= V.Z; return *this; }
    double Size() const { return std::sqrt(X * X + Y * Y + Z * Z); }
    double SizeSquared() const { return X * X + Y * Y + Z * Z; }
    static double Dist(const FVector& V1, const FVector& V2) { return (V1 - V2).Size(); }
    static double DistSquared(const FVector& V1, const FVector& V2) { return (V1 - V2).SizeSquared(); }
    bool IsNearlyZero(double Tol = KINDA_SMALL_NUMBER) const {
        return std::abs(X) <= Tol && std::abs(Y) <= Tol && std::abs(Z) <= Tol;
    }
    FVector GetSafeNormal(double Tol = SMALL_NUMBER) const {
        double S = Size();
        return S > Tol ? (*this / S) : FVector(0.0, 0.0, 0.0);
    }
};
inline constexpr FVector FVector::ZeroVector{0.0, 0.0, 0.0};
inline constexpr FVector FVector::OneVector{1.0, 1.0, 1.0};
inline constexpr FVector FVector::UpVector{0.0, 0.0, 1.0};
inline constexpr FVector FVector::ForwardVector{1.0, 0.0, 0.0};

struct FRotator {
    double Pitch = 0.0;
    double Yaw = 0.0;
    double Roll = 0.0;
    constexpr FRotator() = default;
    constexpr FRotator(double InPitch, double InYaw, double InRoll) : Pitch(InPitch), Yaw(InYaw), Roll(InRoll) {}
    static const FRotator ZeroRotator;
};
inline constexpr FRotator FRotator::ZeroRotator{0.0, 0.0, 0.0};

struct FQuat {
    double X = 0.0, Y = 0.0, Z = 0.0, W = 1.0;
    constexpr FQuat() = default;
    constexpr FQuat(double InX, double InY, double InZ, double InW) : X(InX), Y(InY), Z(InZ), W(InW) {}
    static const FQuat Identity;
};
inline constexpr FQuat FQuat::Identity{0.0, 0.0, 0.0, 1.0};

struct FTransform {
    FRotator Rotation;
    FVector Translation;
    FVector Scale3D{1.0, 1.0, 1.0};
    constexpr FTransform() = default;
    FTransform(const FRotator& R, const FVector& T, const FVector& S = FVector(1.0, 1.0, 1.0))
        : Rotation(R), Translation(T), Scale3D(S) {}
    explicit FTransform(const FVector& T) : Translation(T) {}
    static const FTransform Identity;
    FVector GetLocation() const { return Translation; }
    FRotator GetRotation() const { return Rotation; }
    FVector GetScale3D() const { return Scale3D; }
    void SetLocation(const FVector& V) { Translation = V; }
    void SetScale3D(const FVector& S) { Scale3D = S; }
};
inline const FTransform FTransform::Identity{};

struct FBox {
    FVector Min{0.0, 0.0, 0.0};
    FVector Max{0.0, 0.0, 0.0};
    uint8 IsValid = 0;
    FBox() = default;
    FBox(const FVector& InMin, const FVector& InMax) : Min(InMin), Max(InMax), IsValid(1) {}
    FVector GetSize() const { return Max - Min; }
    FVector GetExtent() const { return (Max - Min) * 0.5; }
    FVector GetCenter() const { return (Min + Max) * 0.5; }
};

struct FBoxSphereBounds {
    FVector Origin{0.0, 0.0, 0.0};
    FVector BoxExtent{50.0, 50.0, 50.0};
    double SphereRadius = 86.6;
    FBox GetBox() const { return FBox(Origin - BoxExtent, Origin + BoxExtent); }
};

struct FMath {
    template <typename T, typename U, typename V>
    static constexpr auto Clamp(T X, U MinV, V MaxV) -> std::common_type_t<T, U, V> {
        using R = std::common_type_t<T, U, V>;
        const R rx = static_cast<R>(X), rmin = static_cast<R>(MinV), rmax = static_cast<R>(MaxV);
        return rx < rmin ? rmin : (rx < rmax ? rx : rmax);
    }
    template <typename T, typename U>
    static constexpr auto Max(T A, U B) -> std::common_type_t<T, U> {
        using R = std::common_type_t<T, U>;
        return static_cast<R>(A) >= static_cast<R>(B) ? static_cast<R>(A) : static_cast<R>(B);
    }
    template <typename T, typename U>
    static constexpr auto Min(T A, U B) -> std::common_type_t<T, U> {
        using R = std::common_type_t<T, U>;
        return static_cast<R>(A) <= static_cast<R>(B) ? static_cast<R>(A) : static_cast<R>(B);
    }
    template <typename T> static T Abs(T A) { return std::abs(A); }
    static bool IsNearlyEqual(double A, double B, double ErrorTolerance = KINDA_SMALL_NUMBER) {
        return std::abs(A - B) <= ErrorTolerance;
    }
    static bool IsNearlyZero(double Value, double ErrorTolerance = KINDA_SMALL_NUMBER) {
        return std::abs(Value) <= ErrorTolerance;
    }
};

template <typename T>
class TArray {
    std::vector<T> Data;
public:
    TArray() = default;
    TArray(std::initializer_list<T> Init) : Data(Init) {}
    int32 Num() const { return static_cast<int32>(Data.size()); }
    bool IsEmpty() const { return Data.empty(); }
    bool IsValidIndex(int32 Idx) const { return Idx >= 0 && Idx < Num(); }
    int32 Add(const T& Item) { Data.push_back(Item); return Num() - 1; }
    int32 Add(T&& Item) { Data.push_back(std::move(Item)); return Num() - 1; }
    int32 AddUnique(const T& Item) {
        for (int32 i = 0; i < Num(); ++i) { if (Data[i] == Item) return i; }
        return Add(Item);
    }
    template <typename... Args> T& Emplace_GetRef(Args&&... InArgs) {
        Data.emplace_back(std::forward<Args>(InArgs)...);
        return Data.back();
    }
    void Empty(int32 Slack = 0) { (void)Slack; Data.clear(); }
    void Reset(int32 NewSize = 0) { Data.clear(); if (NewSize > 0) Data.reserve(static_cast<std::size_t>(NewSize)); }
    void Reserve(int32 Number) { if (Number > 0) Data.reserve(static_cast<std::size_t>(Number)); }
    void SetNum(int32 NewNum) { if (NewNum >= 0) Data.resize(static_cast<std::size_t>(NewNum)); }
    bool Contains(const T& Item) const { return std::find(Data.begin(), Data.end(), Item) != Data.end(); }
    int32 Find(const T& Item) const {
        for (int32 i = 0; i < Num(); ++i) { if (Data[i] == Item) return i; }
        return INDEX_NONE;
    }
    int32 Remove(const T& Item) {
        auto Old = Data.size();
        Data.erase(std::remove(Data.begin(), Data.end(), Item), Data.end());
        return static_cast<int32>(Old - Data.size());
    }
    void RemoveAt(int32 Index) { if (IsValidIndex(Index)) Data.erase(Data.begin() + Index); }
    template <typename Pred> T* FindByPredicate(Pred P) {
        for (auto& E : Data) { if (P(E)) return &E; }
        return nullptr;
    }
    template <typename Pred> const T* FindByPredicate(Pred P) const {
        for (const auto& E : Data) { if (P(E)) return &E; }
        return nullptr;
    }
    template <typename Pred> int32 RemoveAll(Pred P) {
        auto Old = Data.size();
        Data.erase(std::remove_if(Data.begin(), Data.end(), P), Data.end());
        return static_cast<int32>(Old - Data.size());
    }
    T& operator[](int32 Index) { return Data[static_cast<std::size_t>(Index)]; }
    const T& operator[](int32 Index) const { return Data[static_cast<std::size_t>(Index)]; }
    auto begin() { return Data.begin(); }
    auto end() { return Data.end(); }
    auto begin() const { return Data.begin(); }
    auto end() const { return Data.end(); }
};

template <typename K, typename V>
class TMap {
    std::map<K, V> MapData;
public:
    int32 Num() const { return static_cast<int32>(MapData.size()); }
    bool IsEmpty() const { return MapData.empty(); }
    void Empty() { MapData.clear(); }
    bool Contains(const K& Key) const { return MapData.find(Key) != MapData.end(); }
    V* Find(const K& Key) {
        auto It = MapData.find(Key);
        return It != MapData.end() ? &It->second : nullptr;
    }
    const V* Find(const K& Key) const {
        auto It = MapData.find(Key);
        return It != MapData.end() ? &It->second : nullptr;
    }
    V& FindOrAdd(const K& Key) { return MapData[Key]; }
    V& Add(const K& Key, const V& Value) { MapData[Key] = Value; return MapData[Key]; }
    int32 Remove(const K& Key) { return static_cast<int32>(MapData.erase(Key)); }
    V& operator[](const K& Key) { return MapData[Key]; }
    auto begin() { return MapData.begin(); }
    auto end() { return MapData.end(); }
    auto begin() const { return MapData.begin(); }
    auto end() const { return MapData.end(); }
};

template <typename T>
class TObjectPtr {
    T* Ptr = nullptr;
public:
    constexpr TObjectPtr() noexcept = default;
    constexpr TObjectPtr(std::nullptr_t) noexcept : Ptr(nullptr) {}
    template <typename U, typename = std::enable_if_t<std::is_convertible_v<U*, T*>>>
    constexpr TObjectPtr(U* InPtr) noexcept : Ptr(InPtr) {}
    template <typename U, typename = std::enable_if_t<std::is_convertible_v<U*, T*>>>
    TObjectPtr& operator=(U* InPtr) noexcept { Ptr = InPtr; return *this; }
    TObjectPtr& operator=(std::nullptr_t) noexcept { Ptr = nullptr; return *this; }
    T* Get() const noexcept { return Ptr; }
    T* operator->() const noexcept { return Ptr; }
    T& operator*() const noexcept { return *Ptr; }
    operator T*() const noexcept { return Ptr; }
    explicit operator bool() const noexcept { return Ptr != nullptr; }
    bool operator==(std::nullptr_t) const noexcept { return Ptr == nullptr; }
    bool operator!=(std::nullptr_t) const noexcept { return Ptr != nullptr; }
    template <typename U> bool operator==(U* Rhs) const noexcept { return Ptr == Rhs; }
    template <typename U> bool operator!=(U* Rhs) const noexcept { return Ptr != Rhs; }
};

template <typename T>
class TWeakObjectPtr {
    T* Ptr = nullptr;
public:
    constexpr TWeakObjectPtr() noexcept = default;
    constexpr TWeakObjectPtr(std::nullptr_t) noexcept : Ptr(nullptr) {}
    template <typename U, typename = std::enable_if_t<std::is_convertible_v<U*, T*>>>
    TWeakObjectPtr(U* InPtr) noexcept : Ptr(InPtr) {}
    T* Get() const noexcept { return Ptr; }
    bool IsValid() const noexcept { return Ptr != nullptr; }
    void Reset() noexcept { Ptr = nullptr; }
    T* operator->() const noexcept { return Ptr; }
};

template <typename T>
class TSubclassOf {
public:
    TSubclassOf() = default;
    bool operator!=(std::nullptr_t) const { return true; }
};

class UClass {};

class UObject {
public:
    virtual ~UObject() = default;
    static UClass* StaticClass() { static UClass C; return &C; }
    UClass* GetClass() const { return StaticClass(); }
    FName GetFName() const { return FName("Object"); }
    FString GetName() const { return FString("Object"); }
    virtual class UWorld* GetWorld() const { return nullptr; }
    template <typename T>
    T* CreateDefaultSubobject(FName SubobjectName) { (void)SubobjectName; return nullptr; }
};

inline bool IsValid(const UObject* Test) { return Test != nullptr; }

template <typename To, typename From>
To* Cast(From* Src) {
    return dynamic_cast<To*>(Src);
}
template <typename To, typename From>
const To* Cast(const From* Src) {
    return dynamic_cast<const To*>(Src);
}
template <typename To, typename From>
To* Cast(const TObjectPtr<From>& Src) {
    return dynamic_cast<To*>(Src.Get());
}

template <typename T>
T* NewObject(UObject* Outer = nullptr, UClass* Class = nullptr, FName Name = NAME_None) {
    (void)Outer; (void)Class; (void)Name;
    return nullptr;
}

#define check(expr) do { if (!(expr)) {} } while(0)
#define ensure(expr) (static_cast<bool>(expr))
#define ensureMsgf(expr, ...) (static_cast<bool>(expr))
#define UE_LOG(CategoryName, Verbosity, Format, ...) do {} while(0)
#define DECLARE_LOG_CATEGORY_EXTERN(CategoryName, DefaultVerbosity, CompileTimeVerbosity)
#define DEFINE_LOG_CATEGORY(CategoryName)
#define DECLARE_LOG_CATEGORY_STATIC(CategoryName, DefaultVerbosity, CompileTimeVerbosity)

#define DECLARE_DYNAMIC_MULTICAST_DELEGATE(DelegateName) \
    struct DelegateName { \
        void Broadcast() const {} \
        void Clear() {} \
        bool IsBound() const { return false; } \
        template <typename UserClass, typename FuncType> void AddDynamic(UserClass*, FuncType) {} \
        template <typename UserClass, typename FuncType> void RemoveDynamic(UserClass*, FuncType) {} \
    }

#define DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(DelegateName, T1, P1) \
    struct DelegateName { \
        void Broadcast(T1) const {} \
        void Clear() {} \
        bool IsBound() const { return false; } \
        template <typename UserClass, typename FuncType> void AddDynamic(UserClass*, FuncType) {} \
        template <typename UserClass, typename FuncType> void RemoveDynamic(UserClass*, FuncType) {} \
    }

#define DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(DelegateName, T1, P1, T2, P2) \
    struct DelegateName { \
        void Broadcast(T1, T2) const {} \
        void Clear() {} \
        bool IsBound() const { return false; } \
        template <typename UserClass, typename FuncType> void AddDynamic(UserClass*, FuncType) {} \
        template <typename UserClass, typename FuncType> void RemoveDynamic(UserClass*, FuncType) {} \
    }

#define DECLARE_DYNAMIC_MULTICAST_DELEGATE_ThreeParams(DelegateName, T1, P1, T2, P2, T3, P3) \
    struct DelegateName { \
        void Broadcast(T1, T2, T3) const {} \
        void Clear() {} \
        bool IsBound() const { return false; } \
        template <typename UserClass, typename FuncType> void AddDynamic(UserClass*, FuncType) {} \
        template <typename UserClass, typename FuncType> void RemoveDynamic(UserClass*, FuncType) {} \
    }

#define DECLARE_DYNAMIC_MULTICAST_DELEGATE_FourParams(DelegateName, T1, P1, T2, P2, T3, P3, T4, P4) \
    struct DelegateName { \
        void Broadcast(T1, T2, T3, T4) const {} \
        void Clear() {} \
        bool IsBound() const { return false; } \
        template <typename UserClass, typename FuncType> void AddDynamic(UserClass*, FuncType) {} \
        template <typename UserClass, typename FuncType> void RemoveDynamic(UserClass*, FuncType) {} \
    }

enum class EEndPlayReason : uint8 { Destroyed, LevelTransition, EndPlayInEditor, RemovedFromWorld, Quit };
enum class ETickGroup : uint8 { TG_PrePhysics, TG_DuringPhysics, TG_PostPhysics };

struct FTickFunction {
    bool bCanEverTick = false;
    bool bStartWithTickEnabled = false;
    float TickInterval = 0.0f;
    void SetTickFunctionEnable(bool bInEnabled) { bStartWithTickEnabled = bInEnabled; }
};
struct FActorTickFunction : FTickFunction {};
struct FActorComponentTickFunction : FTickFunction {};

struct FTimerHandle {
    uint64 Handle = 0;
    bool IsValid() const { return Handle != 0; }
    void Invalidate() { Handle = 0; }
};

struct FTimerDelegate {
    template <typename UserClass, typename FuncType>
    static FTimerDelegate CreateUObject(UserClass*, FuncType) { return FTimerDelegate{}; }
};

class FTimerManager {
public:
    template <typename UserClass, typename FuncType>
    void SetTimer(FTimerHandle& InOutHandle, UserClass* InObj, FuncType InTimerMethod, float InRate, bool bInLoop = false, float InFirstDelay = -1.0f) {
        (void)InObj; (void)InTimerMethod; (void)InRate; (void)bInLoop; (void)InFirstDelay;
        InOutHandle.Handle = 1;
    }
    void SetTimer(FTimerHandle& InOutHandle, const FTimerDelegate& InDelegate, float InRate, bool bInLoop = false, float InFirstDelay = -1.0f) {
        (void)InDelegate; (void)InRate; (void)bInLoop; (void)InFirstDelay;
        InOutHandle.Handle = 1;
    }
    void ClearTimer(FTimerHandle& InHandle) { InHandle.Invalidate(); }
    bool IsTimerActive(const FTimerHandle& InHandle) const { return InHandle.IsValid(); }
    float GetTimerRemaining(const FTimerHandle& InHandle) const { return InHandle.IsValid() ? 1.0f : -1.0f; }
};

class UWorld : public UObject {
    FTimerManager TimerMgr;
public:
    FTimerManager& GetTimerManager() { return TimerMgr; }
    double GetTimeSeconds() const { return 0.0; }
    float GetDeltaSeconds() const { return 0.016f; }
};

enum class EAttachmentRule : uint8 { KeepRelative, KeepWorld, SnapToTarget };
struct FAttachmentTransformRules {
    EAttachmentRule LocationRule = EAttachmentRule::KeepRelative;
    EAttachmentRule RotationRule = EAttachmentRule::KeepRelative;
    EAttachmentRule ScaleRule = EAttachmentRule::KeepRelative;
    bool bWeldSimulatedBodies = false;
    FAttachmentTransformRules(EAttachmentRule InRule, bool bInWeld = false)
        : LocationRule(InRule), RotationRule(InRule), ScaleRule(InRule), bWeldSimulatedBodies(bInWeld) {}
    FAttachmentTransformRules(EAttachmentRule InLoc, EAttachmentRule InRot, EAttachmentRule InScale, bool bInWeld = false)
        : LocationRule(InLoc), RotationRule(InRot), ScaleRule(InScale), bWeldSimulatedBodies(bInWeld) {}
    static const FAttachmentTransformRules KeepRelativeTransform;
    static const FAttachmentTransformRules KeepWorldTransform;
    static const FAttachmentTransformRules SnapToTargetNotIncludingScale;
    static const FAttachmentTransformRules SnapToTargetIncludingScale;
};
inline const FAttachmentTransformRules FAttachmentTransformRules::KeepRelativeTransform(EAttachmentRule::KeepRelative, false);
inline const FAttachmentTransformRules FAttachmentTransformRules::KeepWorldTransform(EAttachmentRule::KeepWorld, false);
inline const FAttachmentTransformRules FAttachmentTransformRules::SnapToTargetNotIncludingScale(
    EAttachmentRule::SnapToTarget, EAttachmentRule::SnapToTarget, EAttachmentRule::KeepWorld, false);
inline const FAttachmentTransformRules FAttachmentTransformRules::SnapToTargetIncludingScale(EAttachmentRule::SnapToTarget, false);

namespace ECollisionEnabled {
    enum Type : int { NoCollision = 0, QueryOnly = 1, PhysicsOnly = 2, QueryAndPhysics = 3 };
}
enum ECollisionChannel : int {
    ECC_WorldStatic = 0, ECC_WorldDynamic = 1, ECC_Pawn = 2, ECC_Visibility = 3, ECC_Camera = 4, ECC_PhysicsBody = 5
};
enum ECollisionResponse : int { ECR_Ignore = 0, ECR_Overlap = 1, ECR_Block = 2 };

class AActor;

class UActorComponent : public UObject {
public:
    FActorComponentTickFunction PrimaryComponentTick;
    UActorComponent() = default;
    virtual void BeginPlay() {}
    virtual void EndPlay(const EEndPlayReason Reason) { (void)Reason; }
    virtual void TickComponent(float DeltaTime, ETickGroup TickType, FActorComponentTickFunction* ThisTickFunction) {
        (void)DeltaTime; (void)TickType; (void)ThisTickFunction;
    }
    void SetComponentTickEnabled(bool bEnabled) { PrimaryComponentTick.SetTickFunctionEnable(bEnabled); }
    bool IsComponentTickEnabled() const { return PrimaryComponentTick.bStartWithTickEnabled; }
    AActor* GetOwner() const { return nullptr; }
    virtual UWorld* GetWorld() const override { return nullptr; }
    void Activate(bool bReset = false) { (void)bReset; }
    void Deactivate() {}
};

class USceneComponent : public UActorComponent {
    FVector RelLoc;
    FRotator RelRot;
    FVector RelScale{1.0, 1.0, 1.0};
public:
    FBoxSphereBounds Bounds;
    void SetupAttachment(USceneComponent* InParent, FName InSocketName = NAME_None) { (void)InParent; (void)InSocketName; }
    bool AttachToComponent(USceneComponent* InParent, const FAttachmentTransformRules& AttachmentRules, FName InSocketName = NAME_None) {
        (void)InParent; (void)AttachmentRules; (void)InSocketName; return true;
    }
    void DetachFromComponent(const FAttachmentTransformRules& DetachmentRules = FAttachmentTransformRules::KeepRelativeTransform) {
        (void)DetachmentRules;
    }
    virtual bool DoesSocketExist(FName InSocketName) const { (void)InSocketName; return true; }
    virtual FTransform GetSocketTransform(FName InSocketName, int32 TransformSpace = 0) const {
        (void)InSocketName; (void)TransformSpace; return FTransform::Identity;
    }
    virtual FVector GetSocketLocation(FName InSocketName) const { (void)InSocketName; return FVector::ZeroVector; }
    virtual FRotator GetSocketRotation(FName InSocketName) const { (void)InSocketName; return FRotator::ZeroRotator; }
    virtual TArray<FName> GetAllSocketNames() const { return {}; }
    void SetRelativeLocation(const FVector& NewLoc) { RelLoc = NewLoc; }
    void SetRelativeRotation(const FRotator& NewRot) { RelRot = NewRot; }
    void SetRelativeScale3D(const FVector& NewScale) { RelScale = NewScale; }
    void SetRelativeTransform(const FTransform& NewTransform) { RelLoc = NewTransform.Translation; RelRot = NewTransform.Rotation; RelScale = NewTransform.Scale3D; }
    FVector GetRelativeLocation() const { return RelLoc; }
    FRotator GetRelativeRotation() const { return RelRot; }
    FVector GetRelativeScale3D() const { return RelScale; }
    FVector GetComponentLocation() const { return RelLoc; }
    FRotator GetComponentRotation() const { return RelRot; }
    FVector GetComponentScale() const { return RelScale; }
    FTransform GetComponentTransform() const { return FTransform(RelRot, RelLoc, RelScale); }
    FBoxSphereBounds CalcBounds(const FTransform& LocalToWorld) const { (void)LocalToWorld; return Bounds; }
    void SetVisibility(bool bNewVisibility, bool bPropagateToChildren = false) { (void)bNewVisibility; (void)bPropagateToChildren; }
    void SetHiddenInGame(bool NewHidden, bool bPropagateToChildren = false) { (void)NewHidden; (void)bPropagateToChildren; }
};

class UPrimitiveComponent : public USceneComponent {
public:
    void SetCollisionEnabled(ECollisionEnabled::Type NewType) { (void)NewType; }
    void SetCollisionProfileName(FName InCollisionProfileName, bool bUpdateOverlaps = true) { (void)InCollisionProfileName; (void)bUpdateOverlaps; }
    void SetCollisionObjectType(ECollisionChannel Channel) { (void)Channel; }
    void SetCollisionResponseToAllChannels(ECollisionResponse NewResponse) { (void)NewResponse; }
    void SetCollisionResponseToChannel(ECollisionChannel Channel, ECollisionResponse NewResponse) { (void)Channel; (void)NewResponse; }
    void SetGenerateOverlapEvents(bool bInGenerateOverlapEvents) { (void)bInGenerateOverlapEvents; }
    void SetSimulatePhysics(bool bSimulate) { (void)bSimulate; }
};

class UStaticMeshSocket : public UObject {
public:
    FName SocketName;
    FVector RelativeLocation;
    FRotator RelativeRotation;
    FVector RelativeScale{1.0, 1.0, 1.0};
};

class UStaticMesh : public UObject {
    FBox BoundingBox{FVector(-50.0, -50.0, 0.0), FVector(50.0, 50.0, 100.0)};
public:
    FBox GetBoundingBox() const { return BoundingBox; }
    FBoxSphereBounds GetBounds() const { return FBoxSphereBounds{}; }
    UStaticMeshSocket* FindSocket(FName InSocketName) const { (void)InSocketName; return nullptr; }
};

class UStaticMeshComponent : public UPrimitiveComponent {
    UStaticMesh* CurrentMesh = nullptr;
public:
    bool SetStaticMesh(UStaticMesh* NewMesh) { CurrentMesh = NewMesh; return true; }
    UStaticMesh* GetStaticMesh() const { return CurrentMesh; }
    void GetLocalBounds(FVector& Min, FVector& Max) const { Min = FVector(-50.0, -50.0, 0.0); Max = FVector(50.0, 50.0, 100.0); }
};

class UBoxComponent : public UPrimitiveComponent {
public:
    void InitBoxExtent(const FVector& InBoxExtent) { (void)InBoxExtent; }
    void SetBoxExtent(const FVector& InBoxExtent, bool bUpdateOverlaps = true) { (void)InBoxExtent; (void)bUpdateOverlaps; }
    FVector GetScaledBoxExtent() const { return FVector(50.0, 50.0, 50.0); }
    FVector GetUnscaledBoxExtent() const { return FVector(50.0, 50.0, 50.0); }
};

class USphereComponent : public UPrimitiveComponent {
public:
    void InitSphereRadius(float InSphereRadius) { (void)InSphereRadius; }
    void SetSphereRadius(float InSphereRadius, bool bUpdateOverlaps = true) { (void)InSphereRadius; (void)bUpdateOverlaps; }
    float GetScaledSphereRadius() const { return 50.0f; }
};

class AActor : public UObject {
protected:
    TObjectPtr<USceneComponent> RootComponent;
public:
    FActorTickFunction PrimaryActorTick;
    AActor() = default;
    virtual void BeginPlay() {}
    virtual void EndPlay(const EEndPlayReason Reason) { (void)Reason; }
    virtual void Tick(float DeltaTime) { (void)DeltaTime; }
    virtual void OnConstruction(const FTransform& Transform) { (void)Transform; }
    void SetActorTickEnabled(bool bEnabled) { PrimaryActorTick.SetTickFunctionEnable(bEnabled); }
    USceneComponent* GetRootComponent() const { return RootComponent.Get(); }
    bool SetRootComponent(USceneComponent* NewRootComponent) { RootComponent = NewRootComponent; return true; }
    FVector GetActorLocation() const { return RootComponent ? RootComponent->GetComponentLocation() : FVector::ZeroVector; }
    FRotator GetActorRotation() const { return RootComponent ? RootComponent->GetComponentRotation() : FRotator::ZeroRotator; }
    FVector GetActorScale3D() const { return RootComponent ? RootComponent->GetComponentScale() : FVector::OneVector; }
    FTransform GetActorTransform() const { return RootComponent ? RootComponent->GetComponentTransform() : FTransform::Identity; }
    bool SetActorLocation(const FVector& NewLocation) { if (RootComponent) RootComponent->SetRelativeLocation(NewLocation); return true; }
    bool SetActorRotation(const FRotator& NewRotation) { if (RootComponent) RootComponent->SetRelativeRotation(NewRotation); return true; }
    void SetActorScale3D(const FVector& NewScale3D) { if (RootComponent) RootComponent->SetRelativeScale3D(NewScale3D); }
    void GetActorBounds(bool bOnlyCollidingComponents, FVector& Origin, FVector& BoxExtent, bool bIncludeFromChildActors = false) const {
        (void)bOnlyCollidingComponents; (void)bIncludeFromChildActors;
        Origin = FVector::ZeroVector; BoxExtent = FVector(50.0, 50.0, 50.0);
    }
    FTimerManager& GetWorldTimerManager() const {
        static FTimerManager StaticMgr;
        return StaticMgr;
    }
    virtual UWorld* GetWorld() const override { return nullptr; }
    void Destroy() {}
    bool HasAuthority() const { return true; }
    template <typename T>
    T* FindComponentByClass() const { return nullptr; }
};

class APawn : public AActor {};
class UDataAsset : public UObject {};
class UPrimaryDataAsset : public UDataAsset {};
struct FTableRowBase { virtual ~FTableRowBase() = default; };
class UDataTable : public UObject {
public:
    template <typename T> T* FindRow(FName RowName, const char* ContextString, bool bWarnIfRowMissing = true) const {
        (void)RowName; (void)ContextString; (void)bWarnIfRowMissing; return nullptr;
    }
};

class UInputAction : public UDataAsset {};
struct FInputActionValue {
    bool Get() const { return false; }
    template <typename T> T Get() const { return T{}; }
};
enum class ETriggerEvent : uint8 { None, Triggered, Started, Ongoing, Canceled, Completed };
class UEnhancedInputComponent : public UActorComponent {
public:
    template <typename UserClass, typename FuncType>
    void BindAction(const UInputAction* Action, ETriggerEvent TriggerEvent, UserClass* Object, FuncType Func) {
        (void)Action; (void)TriggerEvent; (void)Object; (void)Func;
    }
};
"#
}

fn prepare_stub_dir(
    stub_dir: &Path,
    header_path: &Path,
    reflected: &[ReflectedTypeInfo],
    all_includes: &[String],
) -> Result<(), String> {
    fs::create_dir_all(stub_dir).map_err(|e| e.to_string())?;
    fs::write(stub_dir.join("CoreMinimal.h"), build_ue5_coreminimal_stub()).map_err(|e| e.to_string())?;

    let header_fname = header_path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("Actor.h");
    let header_stem = header_path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("Actor");

    // Materializar <HeaderStem>.generated.h com macros por linha idênticas ao UHT real
    let gen_h_name = format!("{header_stem}.generated.h");
    let mut gen_h = String::new();
    gen_h.push_str("// Auto-generated UHT validation stub for clang++ -fsyntax-only\n");
    gen_h.push_str("#undef CURRENT_FILE_ID\n");
    let fid = format!(
        "FID_{}",
        header_stem
            .chars()
            .map(|c| if c.is_ascii_alphanumeric() { c } else { '_' })
            .collect::<String>()
    );
    gen_h.push_str(&format!("#define CURRENT_FILE_ID {fid}\n"));
    for r in reflected {
        if let Some(ln) = r.generated_body_line_1based {
            if r.kind_macro == "UCLASS" {
                let super_ty = r.base_name.as_deref().unwrap_or("UObject");
                gen_h.push_str(&format!(
                    "#define {fid}_{ln}_GENERATED_BODY \\\npublic: \\\n    using Super = {super_ty}; \\\n    using ThisClass = {}; \\\nprivate:\n",
                    r.type_name
                ));
            } else {
                gen_h.push_str(&format!(
                    "#define {fid}_{ln}_GENERATED_BODY \\\npublic: \\\n    using ThisStruct = {};\n",
                    r.type_name
                ));
            }
        }
    }
    fs::write(stub_dir.join(&gen_h_name), gen_h).map_err(|e| e.to_string())?;

    // Para quaisquer includes padrão da Engine referenciados em .h/.cpp, criar forwarding limpo para CoreMinimal.h
    let std_cpp_headers: BTreeSet<&str> = [
        "cmath", "cstdint", "cstddef", "cstring", "string", "vector", "map", "memory", "algorithm",
        "functional", "utility", "type_traits", "limits", "optional", "array",
    ]
    .into_iter()
    .collect();

    for inc in all_includes {
        let clean = inc.replace('\\', "/");
        if clean == header_fname
            || clean.ends_with(&format!("/{header_fname}"))
            || clean == gen_h_name
            || clean == "CoreMinimal.h"
            || std_cpp_headers.contains(clean.as_str())
        {
            continue;
        }
        // Se já existe ao lado do .h do usuário, não sobrepor
        if let Some(hparent) = header_path.parent()
            && hparent.join(&clean).is_file()
        {
            continue;
        }
        let target = stub_dir.join(&clean);
        if let Some(p) = target.parent() {
            fs::create_dir_all(p).map_err(|e| e.to_string())?;
        }
        if !target.exists() {
            fs::write(&target, "#pragma once\n#include \"CoreMinimal.h\"\n")
                .map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}

fn run_extract_ast(lang: &str, file_path: &Path) -> Result<Value, String> {
    let bytes = fs::read(file_path).map_err(|e| format!("falha ao ler {}: {e}", file_path.display()))?;
    let mut parser = Parser::new();
    match lang {
        "cpp" | "ue5" => parser
            .set_language(&tree_sitter_cpp::LANGUAGE.into())
            .map_err(|e| e.to_string())?,
        "python" | "py" => parser
            .set_language(&tree_sitter_python::LANGUAGE.into())
            .map_err(|e| e.to_string())?,
        other => return Err(format!("linguagem não suportada em --extract-ast: {other}")),
    }
    let tree = parser.parse(&bytes, None).ok_or("falha ao parsear AST")?;
    let root = tree.root_node();

    let mut node_kinds = BTreeSet::new();
    let mut symbols = Vec::new();
    let mut calls = BTreeSet::new();

    fn walk_ast(
        n: Node<'_>,
        src: &[u8],
        kinds: &mut BTreeSet<String>,
        symbols: &mut Vec<String>,
        calls: &mut BTreeSet<String>,
    ) {
        let k = n.kind();
        if n.is_named() {
            kinds.insert(k.to_owned());
        }
        match k {
            "class_specifier" | "struct_specifier" | "function_definition" | "class_definition" => {
                if let Some(nm) = n.child_by_field_name("name") {
                    symbols.push(format!("{k}:{}", node_text(nm, src).trim()));
                } else if let Some(decl) = n.child_by_field_name("declarator") {
                    let first_line = node_text(decl, src).lines().next().unwrap_or("").trim();
                    symbols.push(format!("{k}:{first_line}"));
                }
            }
            "call_expression" | "call" => {
                let func_node = n
                    .child_by_field_name("function")
                    .or_else(|| n.named_child(0));
                if let Some(fn_n) = func_node {
                    let fn_txt = node_text(fn_n, src).trim();
                    if !fn_txt.is_empty() && fn_txt.len() <= 80 {
                        calls.insert(fn_txt.to_owned());
                    }
                }
            }
            _ => {}
        }
        let mut c = n.walk();
        for ch in n.children(&mut c) {
            walk_ast(ch, src, kinds, symbols, calls);
        }
    }

    walk_ast(root, &bytes, &mut node_kinds, &mut symbols, &mut calls);
    let ast_errors = count_ast_errors(root);
    Ok(json!({
        "ok": true,
        "lang": lang,
        "file": file_path.to_string_lossy(),
        "ast_errors": ast_errors,
        "symbols": symbols,
        "calls": calls.into_iter().take(48).collect::<Vec<_>>(),
        "node_kinds": node_kinds.into_iter().collect::<Vec<_>>(),
    }))
}

fn run_verify_ue5(header_path: &Path, source_path: &Path, clang_bin: &Path) -> Result<Ue5VerifyReceipt, String> {
    let h_bytes = fs::read(header_path)
        .map_err(|e| format!("erro lendo header {}: {e}", header_path.display()))?;
    let cpp_bytes = fs::read(source_path)
        .map_err(|e| format!("erro lendo source {}: {e}", source_path.display()))?;
    let h_str = String::from_utf8_lossy(&h_bytes).into_owned();
    let cpp_str = String::from_utf8_lossy(&cpp_bytes).into_owned();

    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_cpp::LANGUAGE.into())
        .map_err(|e| format!("tree-sitter-cpp init: {e}"))?;

    let h_tree = parser.parse(&h_bytes, None).ok_or("tree-sitter falhou no .h")?;
    let cpp_tree = parser.parse(&cpp_bytes, None).ok_or("tree-sitter falhou no .cpp")?;

    let h_root = h_tree.root_node();
    let cpp_root = cpp_tree.root_node();
    let header_ast_errors = count_ast_errors(h_root);
    let source_ast_errors = count_ast_errors(cpp_root);

    let mut violacoes = Vec::new();

    // Inv 1: #pragma once
    let inv_01 = has_pragma_once(h_root, &h_bytes);
    if !inv_01 {
        violacoes.push("INV-01: `#pragma once` ausente no arquivo `.h`.".into());
    }

    // Inv 2: #include "<Stem>.generated.h" presente e estritamente o último #include do .h
    let h_includes = collect_includes(h_root, &h_bytes);
    let cpp_includes = collect_includes(cpp_root, &cpp_bytes);
    let stem = header_path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("");
    let expected_gen = format!("{stem}.generated.h");
    let gen_positions: Vec<usize> = h_includes
        .iter()
        .enumerate()
        .filter_map(|(idx, inc)| if inc.ends_with(".generated.h") { Some(idx) } else { None })
        .collect();
    let inv_02 = gen_positions.len() == 1
        && gen_positions[0] + 1 == h_includes.len()
        && h_includes.last().is_some_and(|last| last == &expected_gen || last.ends_with(".generated.h"));
    if !inv_02 {
        violacoes.push(format!(
            "INV-02: `#include \"{expected_gen}\"` deve existir uma única vez e ser ESTRITAMENTE o último `#include` do `.h` (encontrado: {:?}).",
            h_includes
        ));
    }

    // Inv 3 & Inv 4: UCLASS / USTRUCT presente + GENERATED_BODY() pareado em cada tipo refletido
    let reflected = scan_reflected_types(&h_str);
    let inv_03 = !reflected.is_empty();
    if !inv_03 {
        violacoes.push("INV-03: Nenhuma declaração `UCLASS(...)` ou `USTRUCT(...)` encontrada no `.h`.".into());
    }
    let inv_04 = inv_03 && reflected.iter().all(|r| r.generated_body_line_1based.is_some());
    if !inv_04 {
        for r in &reflected {
            if r.generated_body_line_1based.is_none() {
                violacoes.push(format!(
                    "INV-04: Tipo refletido `{}` (`{}`) não contém `GENERATED_BODY()`.",
                    r.type_name, r.kind_macro
                ));
            }
        }
    }

    // Inv 5 & Inv 6: Zero ponteiros UObject crus sem UPROPERTY/TWeakObjectPtr e zero `new` bruto em UObject
    let h_lines: Vec<&str> = h_str.lines().collect();
    let cpp_lines: Vec<&str> = cpp_str.lines().collect();
    let mut membros_auditados = 0usize;
    let mut raw_ptr_violacoes = Vec::new();
    let mut new_violacoes = Vec::new();
    audit_uobject_fields_and_new(
        h_root,
        &h_bytes,
        &h_lines,
        &mut membros_auditados,
        &mut raw_ptr_violacoes,
        &mut new_violacoes,
    );
    audit_uobject_fields_and_new(
        cpp_root,
        &cpp_bytes,
        &cpp_lines,
        &mut membros_auditados,
        &mut raw_ptr_violacoes,
        &mut new_violacoes,
    );

    let inv_05 = raw_ptr_violacoes.is_empty();
    for v in &raw_ptr_violacoes {
        violacoes.push(format!("INV-05: {v}"));
    }
    let inv_06 = new_violacoes.is_empty();
    for v in &new_violacoes {
        violacoes.push(format!("INV-06: {v}"));
    }

    // Inv 7: Ciclo de vida e macros UE5 válidos (presença de UPROPERTY/UFUNCTION e ausência de bCanEverTick = true sem necessidade)
    let uprop_count = h_str.matches("UPROPERTY(").count();
    let ufunc_count = h_str.matches("UFUNCTION(").count();
    let wasteful_tick = cpp_str.contains("bCanEverTick = true") && !cpp_str.contains("::Tick(") && !cpp_str.contains("::TickComponent(");
    let inv_07 = (uprop_count > 0 || ufunc_count > 0) && !wasteful_tick;
    if !inv_07 {
        violacoes.push(format!(
            "INV-07: Falha de ciclo de vida/reflexão UE5 (UPROPERTY={uprop_count}, UFUNCTION={ufunc_count}, wasteful_tick={wasteful_tick})."
        ));
    }

    // Inv 8: Checagem sintática e de tipos real C++20 via clang++.exe -fsyntax-only -std=c++20
    if !clang_bin.is_file() {
        return Err(format!(
            "BLOQUEADO_DEPENDENCIA_AUSENTE: compilador C++20 não encontrado em {}",
            clang_bin.display()
        ));
    }

    let mut hasher = Sha256::new();
    hasher.update(&h_bytes);
    hasher.update(&cpp_bytes);
    let hash_short: String = hasher
        .finalize()
        .iter()
        .take(6)
        .map(|b| format!("{b:02x}"))
        .collect();

    let temp_root = PathBuf::from(r"D:\Beyond Adonai\Isaque\laboratorio-kev-01\temp")
        .join(format!("ue5_stub_{hash_short}_{}", std::process::id()));
    let mut all_inc = h_includes.clone();
    all_inc.extend(cpp_includes);
    prepare_stub_dir(&temp_root, header_path, &reflected, &all_inc)?;

    let header_dir = header_path.parent().unwrap_or_else(|| Path::new("."));
    let clang_out = Command::new(clang_bin)
        .args([
            "-fsyntax-only",
            "-std=c++20",
            "-Wall",
            "-Wno-unused-parameter",
            "-Wno-unused-private-field",
            "-Wno-pragma-once-outside-header",
            &format!("-I{}", temp_root.display()),
            &format!("-I{}", header_dir.display()),
            &source_path.to_string_lossy(),
        ])
        .output()
        .map_err(|e| format!("falha ao invocar clang++: {e}"))?;

    let _ = fs::remove_dir_all(&temp_root);
    let clang_code = clang_out.status.code().unwrap_or(-1);
    let clang_stderr = String::from_utf8_lossy(&clang_out.stderr).trim().to_owned();
    let inv_08 = clang_code == 0;
    if !inv_08 {
        violacoes.push(format!("INV-08: clang++ -fsyntax-only -std=c++20 retornou exit={clang_code}: {clang_stderr}"));
    }

    let aprovado = inv_01 && inv_02 && inv_03 && inv_04 && inv_05 && inv_06 && inv_07 && inv_08;
    Ok(Ue5VerifyReceipt {
        schema: "isaque.kev01.verificador_fisico_ue5_cpp/1.0",
        header_path: header_path.to_string_lossy().into_owned(),
        source_path: source_path.to_string_lossy().into_owned(),
        aprovado_mecanico: aprovado,
        invariantes_8_de_8: InvariantesUht {
            inv_01_pragma_once: inv_01,
            inv_02_generated_h_ultimo_include: inv_02,
            inv_03_uclass_ou_ustruct_presente: inv_03,
            inv_04_generated_body_pareado: inv_04,
            inv_05_zero_ponteiro_uobject_cru_sem_gc: inv_05,
            inv_06_zero_new_bruto_em_uobject: inv_06,
            inv_07_ciclo_vida_e_macros_ue5_validos: inv_07,
            inv_08_clang_cpp20_fsyntax_only_zero_erros: inv_08,
        },
        violacoes,
        ast_telemetria: AstTelemetria {
            header_ast_errors,
            source_ast_errors,
            includes_header_ordem: h_includes,
            tipos_refletidos: reflected
                .iter()
                .map(|r| format!("{}:{}", r.kind_macro, r.type_name))
                .collect(),
            membros_uobject_auditados: membros_auditados,
            ponteiros_crus_uobject_violadores: raw_ptr_violacoes,
            new_bruto_uobject_violadores: new_violacoes,
            ufunctions_detectadas: ufunc_count,
            uproperties_detectadas: uprop_count,
        },
        clang_cpp20: ClangResult {
            binario: clang_bin.to_string_lossy().into_owned(),
            exit_code: clang_code,
            zero_erros_sintaxe: inv_08,
            stderr_diagnostico: clang_stderr,
        },
    })
}

fn arg_after(args: &[String], flag: &str) -> Option<String> {
    args.iter()
        .position(|a| a == flag)
        .and_then(|i| args.get(i + 1))
        .cloned()
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.iter().any(|a| a == "--extract-ast") {
        let lang = arg_after(&args, "--lang").unwrap_or_else(|| "cpp".into());
        let Some(f) = arg_after(&args, "--file") else {
            eprintln!("{{\"ok\":false,\"error\":\"--file obrigatório\"}}");
            std::process::exit(2);
        };
        match run_extract_ast(&lang, Path::new(&f)) {
            Ok(v) => {
                println!("{}", serde_json::to_string(&v).unwrap());
                std::process::exit(0);
            }
            Err(e) => {
                println!("{}", json!({"ok": false, "error": e}));
                std::process::exit(1);
            }
        }
    }

    let Some(h) = arg_after(&args, "--header") else {
        eprintln!("uso: verificador_fisico_ue5_cpp --header <Arquivo.h> --source <Arquivo.cpp> [--clang <clang++.exe>] [--out <json>]");
        std::process::exit(2);
    };
    let Some(cpp) = arg_after(&args, "--source") else {
        eprintln!("uso: verificador_fisico_ue5_cpp --header <Arquivo.h> --source <Arquivo.cpp> [--clang <clang++.exe>] [--out <json>]");
        std::process::exit(2);
    };
    let clang = arg_after(&args, "--clang")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(DEFAULT_CLANG_WIN));

    match run_verify_ue5(Path::new(&h), Path::new(&cpp), &clang) {
        Ok(recibo) => {
            let txt = serde_json::to_string_pretty(&recibo).unwrap();
            if let Some(out_p) = arg_after(&args, "--out") {
                let _ = fs::write(out_p, &txt);
            }
            println!("{txt}");
            std::process::exit(if recibo.aprovado_mecanico { 0 } else { 1 });
        }
        Err(e) => {
            let err_json = json!({"ok": false, "aprovado_mecanico": false, "erro": e});
            println!("{}", serde_json::to_string_pretty(&err_json).unwrap());
            std::process::exit(2);
        }
    }
}
