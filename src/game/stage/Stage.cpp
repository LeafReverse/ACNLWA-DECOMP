#include <game/stage/Stage.hpp>

#pragma arm
stage::Name stage::GetCurrent()
{
    return static_cast<Name>(Data::s_State.current);
}

bool stage::IsKind(Kind bits, Name id)
{
    if(id == NAME_INVALID) return false;

    return (bits & ~Data::s_KindTable[id]) == 0;
}

stage::Name stage::GetPrev()
{
    return static_cast<Name>(Data::s_State.prev);
}

stage::Name stage::GetNext()
{
    return static_cast<Name>(Data::s_State.next);
}
