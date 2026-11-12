#include <game/ButtonActionControl.hpp>

#pragma arm
int ButtonActionControl::GetPressedIndex() const
{
    if((flags & FLAG_OK_DONE) || (s_Unk94F864 && IsSelectOkOngoing())) return current ? current->GetIndex() : PRESSED_INDEX_NO_NODE;

    return PRESSED_INDEX_NONE;
}

bool ButtonActionControl::IsSelectOkDone() const
{
    if(flags & FLAG_OK_DONE) return true;

    return s_Unk94F864 && IsSelectOkOngoing();
}
