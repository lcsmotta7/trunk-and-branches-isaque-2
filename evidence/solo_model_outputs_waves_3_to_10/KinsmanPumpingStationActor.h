#pragma once

#include "CoreMinimal.h"
#include "Engine/DataTable.h"
#include "Components/StaticMeshComponent.h"
#include "GameFramework/Actor.h"
#include "KinsmanPumpingStationActor.generated.h"

USTRUCT(BlueprintType)
struct FIndustrialAssetManifest : public FTableRowBase {
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Manifest")
    int32 ExpectedLodCount = 3;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Manifest")
    TArray<FName> MaterialSlotNames;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Manifest")
    TArray<FName> RequiredSocketNames;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Manifest")
    FVector ExpectedBoundsMeters{3.0, 1.8, 2.5};
};

UCLASS()
class AKinsmanPumpingStationActor : public AActor {
    GENERATED_BODY()

public:
    AKinsmanPumpingStationActor();

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Industrial")
    TObjectPtr<UStaticMeshComponent> UnitMeshComponent;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Industrial")
    FIndustrialAssetManifest AssetManifest;

    UFUNCTION(BlueprintCallable, Category="Industrial")
    bool ValidateManifestParity() const;
};