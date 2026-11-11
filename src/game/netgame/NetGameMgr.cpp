#include <game/netgame/NetGameMgr.hpp>

#pragma arm
netgame::Type netgame::GetNetgameType()
{
    return static_cast<Type>(NetGameMgr::Get()->netgameType);
}

netgame::PlayerNo netgame::NetGameMgr::GetMyPlayerNo() const
{
    if(!isInNetSession || !isPlayerAssigned) return PLAYER_NO_0;

    return static_cast<PlayerNo>(myPlayerNo);
}
