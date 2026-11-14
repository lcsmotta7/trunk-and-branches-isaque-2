// Copyright 1998-2024 Epic Games, Inc. All Rights Reserved.
#include "CoreMinimal.h"
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

// ----------------------------------------------------------------------------
// IMPLEMENTAÇÃO: ModularBridgeAssetActor.cpp
// ----------------------------------------------------------------------------

#include "ModularBridgeAssetActor.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Components/CapsuleComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Kismet/GameplayStatics.h"
#include "Engine/World.h"

// ----------------------------------------------------------------------------
// PARTE A — Blender 5.2 Headless (Coordenada BRIDGE_3D)
// ----------------------------------------------------------------------------
// Implementação das especificações de coordenadas e dimensões para o Blender 5.2 headless.
// O código abaixo define as variações paramétricas que devem ser geradas pelo Blender.

// Variação 01: Standard (1.00m x 0.16m x 0.28m)
// Posição: (0.0, 0.0, 0.0), Z_min = 0.0
const FVector BRIDGE_3D_VAR_01_STANDARD{ 0.0f, 0.0f, 0.0f };
const FVector BRIDGE_3D_VAR_01_DIMENSIONS{ 1.00f, 0.16f, 0.28f };

// Variação 02: Compact (0.80m x 0.16m x 0.28m)
// Posição: (0.0, 0.65, 0.0), Z_min = 0.0
const FVector BRIDGE_3D_VAR_02_COMPACT{ 0.0f, 0.65f, 0.0f };
const FVector BRIDGE_3D_VAR_02_DIMENSIONS{ 0.80f, 0.16f, 0.28f };

// Variação 03: Heavy (1.25m x 0.18m x 0.32m)
// Posição: (0.0, -0.65, 0.0), Z_min = 0.0
const FVector BRIDGE_3D_VAR_03_HEAVY{ 0.0f, -0.65f, 0.0f };
const FVector BRIDGE_3D_VAR_03_DIMENSIONS{ 1.25f, 0.18f, 0.32f };

// ----------------------------------------------------------------------------
// PARTE B — Unreal Engine 5 C++20 Data-Driven
// ----------------------------------------------------------------------------

AModularBridgeAssetActor::AModularBridgeAssetActor()
{
	PrimaryActorTick.bCanEverTick = false;
}

void AModularBridgeAssetActor::BeginPlay()
{
	Super::BeginPlay();

	// Carregar variação padrão (Standard)
	LoadVariant_Standard();
}

bool AModularBridgeAssetActor::ValidateScale(const FVector& actualDimensions) const
{
	const float tolerance = ScaleTolerance; // 2%
	const float expectedX = CurrentVariant.ExpectedDimensionsMeters.X * 100.0f;
	const float expectedY = CurrentVariant.ExpectedDimensionsMeters.Y * 100.0f;
	const float expectedZ = CurrentVariant.ExpectedDimensionsMeters.Z * 100.0f;

	const float actualX = actualDimensions.X * 100.0f;
	const float actualY = actualDimensions.Y * 100.0f;
	const float actualZ = actualDimensions.Z * 100.0f;

	const float diffX = FMath::Abs(expectedX - actualX);
	const float diffY = FMath::Abs(expectedY - actualY);
	const float diffZ = FMath::Abs(expectedZ - actualZ);

	return (diffX <= tolerance && diffY <= tolerance && diffZ <= tolerance);
}

void AModularBridgeAssetActor::AttachBridgeToPlayer()
{
	if (!GetWorld() || !GetPlayerController())
	{
		return;
	}

	APlayerController* PlayerController = GetPlayerController();
	if (!PlayerController)
	{
		return;
	}

	FVector TargetLocation = PlayerController->GetActorLocation();
	FRotator TargetRotation = PlayerController->GetControlRotation();

	if (BridgeMeshComponent.IsValid())
	{
		BridgeMeshComponent->SetWorldLocation(TargetLocation);
		BridgeMeshComponent->SetWorldRotation(TargetRotation);
		BridgeMeshComponent->SetWorldScale3D(FVector(1.0f, 1.0f, 1.0f));
	}
}

void AModularBridgeAssetActor::LoadVariant_Standard()
{
	CurrentVariant = FModularBridgeVariantRow();
	CurrentVariant.V