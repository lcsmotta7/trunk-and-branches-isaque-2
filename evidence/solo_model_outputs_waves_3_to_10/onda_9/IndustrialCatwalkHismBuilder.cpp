#include "IndustrialCatwalkHismBuilder.h"

AIndustrialCatwalkHismBuilder::AIndustrialCatwalkHismBuilder() {
    PrimaryActorTick.bCanEverTick = false;
    CatwalkHismComponent = CreateDefaultSubobject<UHierarchicalInstancedStaticMeshComponent>(TEXT("CatwalkHismComponent"));
    SetRootComponent(CatwalkHismComponent);
}

int32 AIndustrialCatwalkHismBuilder::RebuildBatchFromRows(const TArray<FIndustrialInstanceTransformRow>& Rows) {
    if (!IsValid(CatwalkHismComponent)) {
        return 0;
    }
    CatwalkHismComponent->ClearInstances();
    TArray<FTransform> BatchTransforms;
    for (const FIndustrialInstanceTransformRow& Row : Rows) {
        BatchTransforms.Add(FTransform(Row.WorldRotation, Row.WorldOffsetCm, Row.InstanceScale));
    }
    if (BatchTransforms.Num() > 0) {
        CatwalkHismComponent->AddInstances(BatchTransforms, false);
    }
    return BatchTransforms.Num();
}