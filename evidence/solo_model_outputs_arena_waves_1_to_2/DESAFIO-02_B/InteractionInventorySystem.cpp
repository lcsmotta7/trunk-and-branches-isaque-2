#include "InteractionInventorySystem.generated.h"

class AInteractableWorldActor;

// ============================================================================
// UInteractionInventoryComponent Implementation
// ============================================================================

UInteractionInventoryComponent::UInteractionInventoryComponent()
{
    MaxInteractionDistanceCm = 250.0f;
    MaxSlots = 16;
}

bool UInteractionInventoryComponent::AddItem(FName ItemId, int32 Quantity)
{
    // Ensure we don't exceed max slots
    if (Entries.Num() >= static_cast<int32>(MaxSlots))
    {
        return false;
    }

    // Find existing entry or create new one
    for (FInventorySlotEntry& Entry : Entries)
    {
        if (Entry.ItemId == ItemId)
        {
            Entry.Quantity += Quantity;
            OnInventoryItemChanged.Broadcast(ItemId, Entry.Quantity);
            return true;
        }
    }

    // Add new entry
    FInventorySlotEntry NewEntry;
    NewEntry.ItemId = ItemId;
    NewEntry.Quantity = Quantity;
    Entries.Add(NewEntry);

    OnInventoryItemChanged.Broadcast(ItemId, Quantity);
    return true;
}

int32 UInteractionInventoryComponent::GetItemQuantity(FName ItemId) const
{
    for (const FInventorySlotEntry& Entry : Entries)
    {
        if (Entry.ItemId == ItemId)
        {
            return Entry.Quantity;
        }
    }
    return 0;
}

bool UInteractionInventoryComponent::TryInteractWithActor(AInteractableWorldActor* TargetActor)
{
    AActor* OwnerActor = GetOwner();
    
    if (!IsValid(OwnerActor) || !IsValid(TargetActor) || !TargetActor->CanInteract())
    {
        return false;
    }

    // Calculate distance in centimeters
    FVector DistanceVector = OwnerActor->GetActorLocation() - TargetActor->GetActorLocation();
    float DistanceCm = FVector::Dist(OwnerActor->GetActorLocation(), TargetActor->GetActorLocation()) * 100.0f;

    if (DistanceCm > MaxInteractionDistanceCm)
    {
        return false;
    }

    return TargetActor->ExecuteInteraction(OwnerActor, this);
}


// ============================================================================
// AInteractableWorldActor Implementation
// ============================================================================

AInteractableWorldActor::AInteractableWorldActor()
{
    RewardItemId = FName("PowerCell_Mk1");
    RewardQuantity = 1;
    CooldownSeconds = 1.5f;
}

bool AInteractableWorldActor::CanInteract() const
{
    return true; // Default implementation, can be overridden in Blueprint
}

bool AInteractableWorldActor::ExecuteInteraction(AActor* Interactor, UInteractionInventoryComponent* InventoryComp)
{
    if (bOnCooldown || !IsValid(Interactor) || !IsValid(InventoryComp))
    {
        return false;
    }

    if (!InventoryComp->AddItem(RewardItemId, RewardQuantity))
    {
        return false;
    }

    bOnCooldown = true;
    OnWorldActorInteracted.Broadcast(Interactor, RewardItemId);

    // Use GetWorldTimerManager() as per rules (NO_TICK, GC_SAFE)
    GetWorldTimerManager().SetTimer(CooldownTimerHandle, [this]() { bOnCooldown = false; }, CooldownSeconds, false);

    return true;
}

void AInteractableWorldActor::EndPlay(const EEndPlayReason::Type Reason) override
{
    // Clear timer to prevent dangling references or invalid operations after death
    GetWorldTimerManager().ClearTimer(CooldownTimerHandle);
    
    Super::EndPlay(Reason);
}