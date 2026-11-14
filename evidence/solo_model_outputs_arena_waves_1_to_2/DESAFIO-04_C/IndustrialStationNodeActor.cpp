#include "IndustrialStationNodeActor.h"

AIndustrialStationNodeActor::AIndustrialStationNodeActor() {
    PrimaryActorTick.bCanEverTick = false;
    
    ReceiverMeshComponent = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("ReceiverMeshComponent"));
    SetRootComponent(ReceiverMeshComponent);
    
    MuzzleModuleComponent = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("MuzzleModuleComponent"));
    MuzzleModuleComponent->SetupAttachment(ReceiverMeshComponent, FName("Socket_Muzzle"));
    
    GripModuleComponent = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("GripModuleComponent"));
    GripModuleComponent->SetupAttachment(ReceiverMeshComponent, FName("Socket_Grip"));
}

bool AIndustrialStationNodeActor::ValidateBoundsMetersToCm(const FVector& ExpectedMeters, float ToleranceRatio) const {
    if (!IsValid(ReceiverMeshComponent) || !IsValid(ReceiverMeshComponent->GetStaticMesh())) {
        return false;
    }
    const FBox BoxCm = ReceiverMeshComponent->GetStaticMesh()->GetBoundingBox();
    const FVector MeasuredCm = BoxCm.GetSize();
    const FVector TargetCm = ExpectedMeters * BlenderMeterToUe5Cm;
    
    const double ErrX = FMath::Abs(MeasuredCm.X - TargetCm.X) / FMath::Max(TargetCm.X, KINDA_SMALL_NUMBER);
    const double ErrY = FMath::Abs(MeasuredCm.Y - TargetCm.Y) / FMath::Max(TargetCm.Y, KINDA_SMALL_NUMBER);
    const double ErrZ = FMath::Abs(MeasuredCm.Z - TargetCm.Z) / FMath::Max(TargetCm.Z, KINDA_SMALL_NUMBER);
    return (ErrX <= ToleranceRatio) && (ErrY <= ToleranceRatio) && (ErrZ <= ToleranceRatio);
}

bool AIndustrialStationNodeActor::ApplyDataDrivenVariant(FName RowName, float ToleranceRatio) {
    if (!IsValid(VariantDataTable) || !IsValid(ReceiverMeshComponent)) {
        return false;
    }
    const FIndustrialStationNodeRow* Row = VariantDataTable->FindRow<FIndustrialStationNodeRow>(RowName, TEXT("StationLookup"));
    if (!IsValid(Row) || !IsValid(Row->StationMesh.Get())) {
        return false;
    }
    ReceiverMeshComponent->SetStaticMesh(Row->StationMesh.Get());
    
    const bool bHasMuzzle = ReceiverMeshComponent->DoesSocketExist(Row->MuzzleSocketName);
    const bool bHasGrip = ReceiverMeshComponent->DoesSocketExist(Row->GripSocketName);
    OnStationNodeActivated.Broadcast(Row->NodeId, bHasMuzzle && bHasGrip);
    return ValidateBoundsMetersToCm(Row->ExpectedDimensionsMeters, ToleranceRatio);
}