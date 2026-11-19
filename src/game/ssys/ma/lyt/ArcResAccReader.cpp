#include <game/ssys/ma/lyt/ArcResAccReader.hpp>

#pragma arm
bool ssys::ma::lyt::ArcResAccReader::ReadArc(const char* name, sead::Heap* heap)
{
    const unsigned long alignment = s_Statics.alignment;
    const unsigned long splitSize = s_Statics.splitSize;

    return ReadArc(name, heap, alignment, splitSize);
}

bool ssys::ma::lyt::ArcResAccReader::ReadArcAll(const char* name)
{
    return ReadArcAll(name, s_Statics.alignment);
}

bool ssys::ma::lyt::ArcResAccReader::ReadArc(const char* name)
{
    const unsigned long alignment = s_Statics.alignment;
    const unsigned long splitSize = s_Statics.splitSize;

    return ReadArc(name, alignment, splitSize);
}
