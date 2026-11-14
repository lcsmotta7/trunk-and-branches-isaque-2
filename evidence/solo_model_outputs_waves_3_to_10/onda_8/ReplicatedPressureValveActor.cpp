#include "ReplicatedPressureValveActor.h"

AReplicatedPressureValveActor::AReplicatedPressureValveActor() {
    PrimaryActorTick.bCanEverTick = false;
    bReplicates = true;
    ValveBodyMesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("ValveBodyMesh"));
    SetRootComponent(ValveBodyMesh);
}

void AReplicatedPressureValveActor::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const {
    Super::GetLifetimeReplicatedProps(OutLifetimeProps);
    DOREPLIFETIME(AReplicatedPressureValveActor, ReplicatedPressureBar);
    DOREPLIFETIME(AReplicatedPressureValveActor, bValveOpen);
}

void AReplicatedPressureValveActor::OnRep_PressureBar() {
    OnValvePressureReplicated.Broadcast(ReplicatedPressureBar);
}

void AReplicatedPressureValveActor::ServerSetValveState_Implementation(float TargetPressureBar, bool bOpen) {
    if (!HasAuthority()) {
        return;
    }
    ReplicatedPressureBar = FMath::Clamp(TargetPressureBar, 0.0f, 250.0f);
    bValveOpen = bOpen;
    OnRep_PressureBar();
}