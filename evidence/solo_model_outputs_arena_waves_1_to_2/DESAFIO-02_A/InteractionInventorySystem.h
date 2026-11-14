#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "Components/ActorComponent.h"
#include "InteractionInventorySystem.generated.h"

// ============================================================================
// BLOCO 2: DEFINIÇÕES DE DADOS (STRUCTS E CLASSES)
// ============================================================================

/**
 * Entrada de inventário para slots.
 */
USTRUCT(BlueprintType)
struct FInventorySlotEntry
{
    GENERATED_BODY()

public:
    FName ItemId;
    int32 Quantity;

    FInventorySlotEntry() = default;
    FInventorySlotEntry(const FName& InItemId, const int32 InQuantity) : ItemId(InItemId), Quantity(InQuantity) {}
};

/**
 * Componente de interação para inventário.
 */
UCLASS(ClassGroup=(Custom), meta=(BlueprintSpawnableComponent))
class INTERACTIONINVENTORYSYSTEM_API UInteractionInventoryComponent : public UActorComponent
{
    GENERATED_BODY()

public:
    UInteractionInventoryComponent();
    virtual ~UInteractionInventoryComponent() override;

    // Construtor para inicialização rápida (apenas para Blueprint)
    UFUNCTION(BlueprintCallable, Category = "InteractionInventory")
    void InitializeInventory(const TArray<FName>& InitialItemIds);

    // Função para adicionar item ao inventário
    UFUNCTION(BlueprintCallable, Category = "InteractionInventory")
    bool AddItemToInventory(const FName& ItemId, const int32 Quantity, bool bForceAdd = false);

    // Função para remover item do inventário
    UFUNCTION(BlueprintCallable, Category = "InteractionInventory")
    bool RemoveItemFromInventory(const FName& ItemId, const int32 Quantity);

    // Função para verificar se o item está no inventário
    UFUNCTION(BlueprintCallable, Category = "InteractionInventory")
    bool IsItemInInventory(const FName& ItemId) const;

    // Função para obter a quantidade do item no inventário
    UFUNCTION(BlueprintCallable, Category = "InteractionInventory")
    int32 GetItemQuantity(const FName& ItemId) const;

    // Função para obter o inventário completo
    UFUNCTION(BlueprintCallable, Category = "InteractionInventory")
    void GetAllInventoryItems(TArray<FName>& OutItemIds);

protected:
    virtual void Deactivate() override;
    virtual void Activate() override;

private:
    TMap<FName, int32> InventoryItems;
};

/**
 * Ator interativo do mundo.
 */
UCLASS()
class INTERACTIONINVENTORYSYSTEM_API AInteractableWorldActor : public AActor
{
    GENERATED_BODY()

public:
    AInteractableWorldActor();
    virtual ~AInteractableWorldActor() override;

    UFUNCTION(BlueprintCallable, Category = "InteractionInventory")
    void InteractWith(const FString& InteractionType);

private:
};