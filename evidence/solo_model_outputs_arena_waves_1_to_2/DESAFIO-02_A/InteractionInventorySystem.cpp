// File: InteractionInventorySystem.cpp
// Project: Isaque 2.0 Soberano (0.15.0) | System: VICOP (Extrator Perceptual)
// Status: COMPRESSÃO ATIVA | Prompt: [VETOR-ANCORA-EN]

#include "InteractionInventorySystem.h"
#include "Components/ActorComponent.h"
#include "GameFramework/Actor.h"
#include "Kismet/GameplayStatics.h"
#include "Engine/World.h"

// ============================================================================
// UInteractionInventoryComponent Implementation
// ============================================================================

UInteractionInventoryComponent::UInteractionInventoryComponent()
{
    PrimaryComponentTick.bCanEverTick = false; // Ciclo de Vida: Componente sem tick
}

UInteractionInventoryComponent::~UInteractionInventoryComponent()
{
    // Limpeza final se necessário
}

void UInteractionInventoryComponent::InitializeInventory(const TArray<FName>& InitialItemIds)
{
    for (const FName& ItemId : InitialItemIds)
    {
        AddItemToInventory(ItemId, 1, false);
    }
}

bool UInteractionInventoryComponent::AddItemToInventory(const FName& ItemId, const int32 Quantity, bool bForceAdd)
{
    if (Quantity <= 0)
    {
        return false;
    }

    int32 CurrentQuantity = GetItemQuantity(ItemId);
    if (bForceAdd || CurrentQuantity < Quantity)
    {
        InventoryItems[ItemId] += Quantity;
        return true;
    }
    return false;
}

bool UInteractionInventoryComponent::RemoveItemFromInventory(const FName& ItemId, const int32 Quantity)
{
    if (InventoryItems.Contains(ItemId))
    {
        int32 CurrentQuantity = InventoryItems[ItemId];
        if (CurrentQuantity >= Quantity)
        {
            InventoryItems[ItemId] -= Quantity;
            if (InventoryItems[ItemId] <= 0)
            {
                InventoryItems.Remove(ItemId);
            }
            return true;
        }
    }
    return false;
}

bool UInteractionInventoryComponent::IsItemInInventory(const FName& ItemId) const
{
    return InventoryItems.Contains(ItemId);
}

int32 UInteractionInventoryComponent::GetItemQuantity(const FName& ItemId) const
{
    if (InventoryItems.Contains(ItemId))
    {
        return InventoryItems[ItemId];
    }
    return 0;
}

void UInteractionInventoryComponent::GetAllInventoryItems(TArray<FName>& OutItemIds)
{
    OutItemIds.Empty();
    for (const auto& Pair : InventoryItems)
    {
        OutItemIds.Add(Pair.Key);
    }
}

void UInteractionInventoryComponent::Activate()
{
    // Ativação do componente
}

void UInteractionInventoryComponent::Deactivate()
{
    // Desativação do componente
}

// ============================================================================
// AInteractableWorldActor Implementation
// ============================================================================

AInteractableWorldActor::AInteractableWorldActor()
{
    PrimaryActorTick.bCanEverTick = false; // Ciclo de Vida: Ator sem tick
}

AInteractableWorldActor::~AInteractableWorldActor()
{
    // Limpeza final se necessário
}

void AInteractableWorldActor::InitializeActor()
{
    // Inicialização rápida para Blueprint
}

void AInteractableWorldActor::BeginPlay()
{
    Super::BeginPlay();
    // Lógica de inicialização específica do ator
}

void AInteractableWorldActor::Tick(float DeltaTime)
{
    // Tick desabilitado por padrão, mas mantido para compatibilidade com Blueprint
    // Se necessário, lógica de temporizador pode ser adicionada aqui
}