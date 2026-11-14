#pragma once

#include "CoreMinimal.h"
#include "Engine/DataTable.h"
#include "Components/HierarchicalInstancedStaticMeshComponent.h"
#include "GameFramework/Actor.h"
#include "IndustrialCatwalkHismBuilder.generated.h"

USTRUCT(BlueprintType)
struct FIndustrialInstanceTransformRow : public FTableRowBase {
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="PCG")
    FVector WorldOffsetCm{0.0, 0.0, 0.0};

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="PCG")
    FRotator WorldRotation{0.0, 0.0, 0.0};

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="PCG")
    FVector InstanceScale{1.0, 1.0, 1.0};
};

UCLASS()
class AIndustrialCatwalkHismBuilder : public AActor {
    GENERATED_BODY()

public:
    AIndustrialCatwalkHismBuilder();

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Industrial|HISM")
    TObjectPtr<UHierarchicalInstancedStaticMeshComponent> CatwalkHismComponent;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Industrial|Data")
    TObjectPtr<UDataTable> LayoutDataTable;

    UFUNCTION(BlueprintCallable, Category="Industrial|HISM")
    int32 RebuildBatchFromRows(const TArray<FIndustrialInstanceTransformRow>& Rows);
};