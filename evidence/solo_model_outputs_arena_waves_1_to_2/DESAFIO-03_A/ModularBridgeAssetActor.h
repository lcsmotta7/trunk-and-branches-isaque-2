// Copyright 1998-2024 Epic Games, Inc. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"
#include "ModularBridgeAssetActor.generated.h"

// ----------------------------------------------------------------------------
// PARTE A — Blender 5.2 Headless (Coordenada BRIDGE_3D)
// ----------------------------------------------------------------------------
// Nota: Esta seção contém apenas as especificações de coordenadas e dimensões
// para o Blender 5.2 headless. O código C++ abaixo implementa a leitura e uso
// desses dados.

// Coordenada BRIDGE_3D (Z-up, escala METRIC):
// Var_01_Standard: (0.0, 0.0, 0.0), scale_length = 1.0, dimensões = 1.00m x 0.16m x 0.28m
// Var_02_Compact:   (0.0, 0.65, 0.0), scale_length = 1.0, dimensões = 0.80m x 0.16m x 0.28m
// Var_03_Heavy:     (0.0, -0.65, 0.0), scale_length = 1.0, dimensões = 1.25m x 0.18m x 0.32m

// ----------------------------------------------------------------------------
// PARTE B — Unreal Engine 5 C++20 Data-Driven
// ----------------------------------------------------------------------------

USTRUCT(BlueprintType)
struct FModularBridgeVariantRow : public FTableRowBase
{
	GENERATED_BODY()

public:
	// Membro UObject: referência à estática gerada pelo Blender headless
	// [FIX] UPROPERTY para rastreio do GC e ciclo de vida
	UPROPERTY(EditDefaultsOnly, Category = "DataDriven")
	TObjectPtr<UStaticMesh> VariantMesh;

	// Dimensões esperadas em metros (X, Y, Z)
	FVector ExpectedDimensionsMeters{ 1.00f, 0.16f, 0.28f };

	// Nomes dos sockets de mira e agarre
	FName MuzzleSocketName = FName("Socket_Muzzle");
	FName GripSocketName = FName("Socket_Grip");
};

UCLASS()
class MODULAR_BRIDGE_API AModularBridgeAssetActor : public AActor
{
	GENERATED_BODY()

public:
	AModularBridgeAssetActor();

protected:
	virtual void BeginPlay() override;

private:
	// Componente estática do módulo (apenas para referência, não é montada)
	// [FIX] UPROPERTY para rastreio do GC e ciclo de vida
	UPROPERTY(EditDefaultsOnly, Category = "Mesh")
	TObjectPtr<UStaticMeshComponent> BridgeMeshComponent;

	// Dados da variação carregada
	// [FIX] UPROPERTY para rastreio do GC e ciclo de vida
	UPROPERTY(EditDefaultsOnly, Category = "DataDriven")
	FModularBridgeVariantRow CurrentVariant;

	// Tolerância de escala (2%)
	const float ScaleTolerance = 0.02f;

	// Validação cruzada de escala: ExpectedMeters * 100.0 -> tolerância ±2%
	bool ValidateScale(const FVector& actualDimensions) const;

	// Acoplamento via Transform (sem escala)
	void AttachBridgeToPlayer();

	// Funções para cada variação (apenas para referência, não implementadas aqui)
	virtual void LoadVariant_Standard() override;
	virtual void LoadVariant_Compact() override;
	virtual void LoadVariant_Heavy() override;
};