#pragma once

#include "CoreMinimal.h"
#include "Engine/DataTable.h"
#include "Components/StaticMeshComponent.h"
#include "GameFramework/Actor.h"
#include "IndustrialStationNodeActor.generated.h"

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FOnStationNodeActivatedSignature, FName, NodeId, bool, bSocketsVerified);

USTRUCT(BlueprintType)
struct FIndustrialStationNodeRow : public FTableRowBase {
    GENERATED_BODY()
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Station") FName NodeId = FName("Station_01");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Station") TObjectPtr<UStaticMesh> StationMesh = nullptr;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Station") FVector ExpectedDimensionsMeters{5.00, 2.20, 3.20};
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Station") FName MuzzleSocketName = FName("Socket_Muzzle");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Station") FName GripSocketName = FName("Socket_Grip");
};

UCLASS()
class AIndustrialStationNodeActor : public AActor {
    GENERATED_BODY()
public:
    AIndustrialStationNodeActor();
    static constexpr double BlenderMeterToUe5Cm = 100.0;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components") TObjectPtr<UStaticMeshComponent> ReceiverMeshComponent;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components") TObjectPtr<UStaticMeshComponent> MuzzleModuleComponent;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components") TObjectPtr<UStaticMeshComponent> GripModuleComponent;
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Station") TObjectPtr<UDataTable> VariantDataTable;
    UPROPERTY(BlueprintAssignable, Category="Station|Events") FOnStationNodeActivatedSignature OnStationNodeActivated;
    UFUNCTION(BlueprintCallable, Category="Station") bool ApplyDataDrivenVariant(FName RowName, float ToleranceRatio = 0.02f);
    UFUNCTION(BlueprintCallable, Category="Station") bool ValidateBoundsMetersToCm(const FVector& ExpectedMeters, float ToleranceRatio = 0.02f) const;
};