#include "ModularBridgeAssetActor.h"
#include "Engine/DataTable.h"
#include "Components/StaticMeshComponent.h"
#include "GameFramework/Actor.h"
#include "Kismet/GameplayStatics.h"

AModularBridgeAssetActor::AModularBridgeAssetActor() {
    PrimaryActorTick.bCanEverTick = false;
    
    ReceiverMeshComponent = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("ReceiverMeshComponent"));
    SetRootComponent(ReceiverMeshComponent);
    
    MuzzleModuleComponent = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("MuzzleModuleComponent"));
    MuzzleModuleComponent->SetupAttachment(ReceiverMeshComponent, FName("Socket_Muzzle"), FAttachmentTransformRules::SnapToTargetNotIncludingScale);
    
    GripModuleComponent = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("GripModuleComponent"));
    GripModuleComponent->SetupAttachment(ReceiverMeshComponent, FName("Socket_Grip"), FAttachmentTransformRules::SnapToTargetNotIncludingScale);
}

bool AModularBridgeAssetActor::ValidateBoundsMetersToCm(const FVector& ExpectedMeters, float ToleranceRatio) const {
    if (!IsValid(ReceiverMeshComponent) || !IsValid(ReceiverMeshComponent->GetStaticMesh())) {
        return false;
    }
    
    const FBox& Box = ReceiverMeshComponent->GetStaticMesh()->GetBoundingBox();
    const FVector MeasuredCm = Box.GetSize();
    const FVector TargetCm = ExpectedMeters * 100.0;
    
    const double ErrX = FMath::Abs(MeasuredCm.X - TargetCm.X) / FMath::Max(TargetCm.X, KINDA_SMALL_NUMBER);
    const double ErrY = FMath::Abs(MeasuredCm.Y - TargetCm.Y) / FMath::Max(TargetCm.Y, KINDA_SMALL_NUMBER);
    const double ErrZ = FMath::Abs(MeasuredCm.Z - TargetCm.Z) / FMath::Max(TargetCm.Z, KINDA_SMALL_NUMBER);
    
    return (ErrX <= ToleranceRatio) && (ErrY <= ToleranceRatio) && (ErrZ <= ToleranceRatio);
}

bool AModularBridgeAssetActor::ApplyDataDrivenVariant(FName RowName, float ToleranceRatio) {
    if (!IsValid(VariantDataTable) || !IsValid(ReceiverMeshComponent)) {
        return false;
    }
    
    FModularBridgeVariantRow* Row = VariantDataTable->FindRow<FModularBridgeVariantRow>(RowName, TEXT("BridgeLookup"));
    
    if (Row == nullptr) {
        return false;
    }
    
    if (!IsValid(Row->VariantMesh.Get())) {
        return false;
    }
    
    ReceiverMeshComponent->SetStaticMesh(Row->VariantMesh.Get());
    
    bool bMuzzleExists = ReceiverMeshComponent->DoesSocketExist(Row->MuzzleSocketName);
    bool bGripExists = ReceiverMeshComponent->DoesSocketExist(Row->GripSocketName);
    
    if (!bMuzzleExists || !bGripExists) {
        return false;
    }
    
    MuzzleModuleComponent->AttachToComponent(ReceiverMeshComponent, FAttachmentTransformRules::SnapToTargetNotIncludingScale, Row->MuzzleSocketName);
    GripModuleComponent->AttachToComponent(ReceiverMeshComponent, FAttachmentTransformRules::SnapToTargetNotIncludingScale, Row->GripSocketName);
    
    const bool bOk = ValidateBoundsMetersToCm(Row->ExpectedDimensionsMeters, ToleranceRatio);
    
    OnBridgeVariantApplied.Broadcast(Row->VariantId, bOk);
    
    return bOk;
}