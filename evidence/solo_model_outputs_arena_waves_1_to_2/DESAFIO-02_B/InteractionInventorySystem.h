#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Components/SphereComponent.h"
#include "GameFramework/Actor.h"
#include "TimerManager.h"
#include "InteractionInventorySystem.generated.h"

class AInteractableWorldActor;

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FOnInventoryItemChangedSignature, FName, ItemId, int32, NewQuantity);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FOnWorldActorInteractedSignature, AActor*, Interactor, FName, GrantedItemId);

USTRUCT(BlueprintType)
struct FInventorySlotEntry {
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Inventory")
    FName ItemId = NAME_None;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Inventory")
    int32 Quantity = 0;
};

UCLASS(ClassGroup=(Custom), meta=(BlueprintSpawnableComponent))
class UInteractionInventoryComponent : public UActorComponent {
    GENERATED_BODY()

public:
    UInteractionInventoryComponent();

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Interaction")
    float MaxInteractionDistanceCm = 250.0f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Inventory")
    int32 MaxSlots = 16;

    UPROPERTY(BlueprintAssignable, Category="Inventory|Events")
    FOnInventoryItemChangedSignature OnInventoryItemChanged;

    UFUNCTION(BlueprintCallable, Category="Inventory")
    bool AddItem(FName ItemId, int32 Quantity);

    UFUNCTION(BlueprintCallable, Category="Inventory")
    int32 GetItemQuantity(FName ItemId) const;

    UFUNCTION(BlueprintCallable, Category="Interaction")
    bool TryInteractWithActor(AInteractableWorldActor* TargetActor);

private:
    UPROPERTY(VisibleAnywhere, Category="Inventory")
    TArray<FInventorySlotEntry> Entries;
};

UCLASS()
class AInteractableWorldActor : public AActor {
    GENERATED_BODY()

public:
    AInteractableWorldActor();

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components")
    TObjectPtr<UStaticMeshComponent> MeshComponent;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components")
    TObjectPtr<USphereComponent> InteractionSphere;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Interaction")
    FName RewardItemId = FName("PowerCell_Mk1");

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Interaction")
    int32 RewardQuantity = 1;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Interaction")
    float CooldownSeconds = 1.5f;

    UPROPERTY(BlueprintAssignable, Category="Interaction|Events")
    FOnWorldActorInteractedSignature OnWorldActorInteracted;

    UFUNCTION(BlueprintCallable, Category="Interaction")
    bool CanInteract() const;

    UFUNCTION(BlueprintCallable, Category="Interaction")
    bool ExecuteInteraction(AActor* Interactor, UInteractionInventoryComponent* InventoryComp);

protected:
    virtual void EndPlay(const EEndPlayReason::Type Reason) override;

private:
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Interaction")
    FTimerHandle CooldownTimerHandle;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Interaction")
    bool bOnCooldown = false;
};