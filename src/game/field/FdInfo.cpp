#include <game/field/FdInfo.hpp>

#pragma arm
Field* FdInfo::GetCurrentField()
{
    return s_pCurrentField;
}
