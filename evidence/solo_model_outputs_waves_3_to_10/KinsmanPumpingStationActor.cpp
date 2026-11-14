#include "KinsmanPumpingStationActor.h"

AKinsmanPumpingStationActor::AKinsmanPumpingStationActor() {
    PrimaryActorTick.bCanEverTick = false;
    UnitMeshComponent = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("UnitMeshComponent"));
    SetRootComponent(UnitMeshComponent);

    AssetManifest.ExpectedLodCount = 3;
    AssetManifest.MaterialSlotNames.Add(FName("M_Industrial_Concrete"));
    AssetManifest.MaterialSlotNames.Add(FName("M_Brushed_Steel"));
    AssetManifest.MaterialSlotNames.Add(FName("M_Pressurized_Copper"));
    AssetManifest.MaterialSlotNames.Add(FName("M_Tech_Glass"));

    AssetManifest.RequiredSocketNames.Add(FName("Socket_Flow_In"));
    AssetManifest.RequiredSocketNames.Add(FName("Socket_Flow_Out"));
    AssetManifest.RequiredSocketNames.Add(FName("Socket_Walkway_Link"));
}

bool AKinsmanPumpingStationActor::ValidateManifestParity() const {
    if (!IsValid(UnitMeshComponent) || AssetManifest.ExpectedLodCount < 3) {
        return false;
    }
    for (const FName& Sock : AssetManifest.RequiredSocketNames) {
        if (!UnitMeshComponent->DoesSocketExist(Sock)) {
            return false;
        }
    }
    return AssetManifest.MaterialSlotNames.Num() == 4;
}