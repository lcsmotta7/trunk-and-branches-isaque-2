#include "InteractionInventorySystem.h"

UInteractionInventoryComponent::UInteractionInventoryComponent() {
    PrimaryComponentTick.bCanEverTick = false;
}

bool UInteractionInventoryComponent::AddItem(FName ItemId, int32 Quantity) {
    if (ItemId.IsNone() || Quantity <= 0) return false;
    for (FInventorySlotEntry& Slot : Entries) {
        if (Slot.ItemId == ItemId) {
            Slot.Quantity += Quantity;
            OnInventoryItemChanged.Broadcast(ItemId, Slot.Quantity);
            return true;
        }
    }
    if (Entries.Num() >= MaxSlots) return false;
    FInventorySlotEntry NewSlot;
    NewSlot.ItemId = ItemId;
    NewSlot.Quantity = Quantity;
    Entries.Add(NewSlot);
    OnInventoryItemChanged.Broadcast(ItemId, Quantity);
    return true;
}

int32 UInteractionInventoryComponent::GetItemQuantity(FName ItemId) const {
    for (const FInventorySlotEntry& Slot : Entries) {
        if (Slot.ItemId == ItemId) {
            return Slot.Quantity;
        }
    }
    return 0;
}

bool UInteractionInventoryComponent::TryInteractWithActor(AInteractableWorldActor* TargetActor) {
    AActor* OwnerActor = GetOwner();
    if (!IsValid(OwnerActor) || !IsValid(TargetActor) || !TargetActor->CanInteract()) {
        return false;
    }
    const double DistCm = FVector::Dist(OwnerActor->GetActorLocation(), TargetActor->GetActorLocation());
    if (DistCm > static_cast<double>(MaxInteractionDistanceCm)) {
        return false;
    }
    return TargetActor->ExecuteInteraction(OwnerActor, this);
}

AInteractableWorldActor::AInteractableWorldActor() {
    PrimaryActorTick.bCanEverTick = false;
    DisplayMesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("DisplayMesh"));
    SetRootComponent(DisplayMesh);

    InteractionSphere = CreateDefaultSubobject<USphereComponent>(TEXT("InteractionSphere"));
    InteractionSphere->InitSphereRadius(250.0f);
    InteractionSphere->SetupAttachment(DisplayMesh);
}

bool AInteractableWorldActor::CanInteract() const {
    return !bOnCooldown && IsValid(GetOwner());
}

bool AInteractableWorldActor::ExecuteInteraction(AActor* Interactor, UInteractionInventoryComponent* InventoryComp) {
    if (bOnCooldown || !IsValid(Interactor) || !IsValid(InventoryComp)) {
        return false;
    }
    if (!InventoryComp->AddItem(RewardItemId, RewardQuantity)) {
        return false;
    }
    bOnCooldown = true;
    OnWorldActorInteracted.Broadcast(Interactor, RewardItemId);
    GetWorldTimerManager().SetTimer(CooldownTimerHandle, [this]() { bOnCooldown = false; }, CooldownSeconds, false);
    return true;
}

void AInteractableWorldActor::EndPlay(const EEndPlayReason Reason) {
    GetWorldTimerManager().ClearTimer(CooldownTimerHandle);
    Super::EndPlay(Reason);
}