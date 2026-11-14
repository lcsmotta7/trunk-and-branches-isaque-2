#pragma once

#include "CoreMinimal.h"
#include "Components/StaticMeshComponent.h"
#include "GameFramework/Actor.h"
#include "Net/UnrealNetwork.h"
#include "ReplicatedPressureValveActor.generated.h"

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnValvePressureReplicatedSignature, float, CurrentPressureBar);

UCLASS()
class AReplicatedPressureValveActor : public AActor {
    GENERATED_BODY()

public:
    AReplicatedPressureValveActor();

    virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Industrial|Components")
    TObjectPtr<UStaticMeshComponent> ValveBodyMesh;

    UPROPERTY(ReplicatedUsing=OnRep_PressureBar, EditAnywhere, BlueprintReadOnly, Category="Industrial|Net")
    float ReplicatedPressureBar = 1.0f;

    UPROPERTY(Replicated, VisibleAnywhere, BlueprintReadOnly, Category="Industrial|Net")
    bool bValveOpen = false;

    UPROPERTY(BlueprintAssignable, Category="Industrial|Events")
    FOnValvePressureReplicatedSignature OnValvePressureReplicated;

    UFUNCTION()
    void OnRep_PressureBar();

    UFUNCTION(Server, Reliable, BlueprintCallable, Category="Industrial|Net")
    void ServerSetValveState(float TargetPressureBar, bool bOpen);
};