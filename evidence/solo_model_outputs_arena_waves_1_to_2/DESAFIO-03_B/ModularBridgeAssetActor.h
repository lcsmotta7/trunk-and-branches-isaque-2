#pragma once
#include "CoreMinimal.h"
#include "Engine/DataTable.h"
#include "Components/StaticMeshComponent.h"
#include "GameFramework/Actor.h"
#include "ModularBridgeAssetActor.generated.h"

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FOnBridgeVariantAppliedSignature, FName, VariantId, bool, bSocketsVerified);

USTRUCT(BlueprintType)
struct FModularBridgeVariantRow : public FTableRowBase {
    GENERATED_BODY()
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Bridge") FName VariantId = FName("Var_01_Standard");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Bridge") TObjectPtr<UStaticMesh> VariantMesh = nullptr;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Bridge") FVector ExpectedDimensionsMeters{1.00, 0.16, 0.28};
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Bridge") FName MuzzleSocketName = FName("Socket_Muzzle");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Bridge") FName GripSocketName = FName("Socket_Grip");
};

UCLASS()
class AModularBridgeAssetActor : public AActor {
    GENERATED_BODY()
public:
    AModularBridgeAssetActor();
    static constexpr double BlenderMeterToUe5Cm = 100.0;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components") TObjectPtr<UStaticMeshComponent> ReceiverMeshComponent;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components") TObjectPtr<UStaticMeshComponent> MuzzleModuleComponent;
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components") TObjectPtr<UStaticMeshComponent> GripModuleComponent;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Bridge") TObjectPtr<UDataTable> VariantDataTable;
    UPROPERTY(BlueprintAssignable, Category="Bridge|Events") FOnBridgeVariantAppliedSignature OnBridgeVariantApplied;
    UFUNCTION(BlueprintCallable, Category="Bridge") bool ApplyDataDrivenVariant(FName RowName, float ToleranceRatio = 0.02f);
    UFUNCTION(BlueprintCallable, Category="Bridge") bool ValidateBoundsMetersToCm(const FVector& ExpectedMeters, float ToleranceRatio = 0.02f) const;
};