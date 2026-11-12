#pragma once

#include <game/ButtonActionNode.hpp>

class ButtonActionControl
{
    public:
    enum Flag
    {
        FLAG_OK_DONE = 1
    };

    enum
    {
        PRESSED_INDEX_NONE = -1,
        PRESSED_INDEX_NO_NODE = -2
    };

    virtual ~ButtonActionControl();

    bool IsSelectOkDone() const;
    bool IsSelectOkOngoing() const { return func == &ButtonActionControl::State_Selecting; }
    int GetPressedIndex() const;

    private:
    typedef void (ButtonActionControl::*Func)();

    void State_Selecting();

    unsigned char unk4[0xB0];
    ButtonActionNode* current;
    Func func;
    unsigned char unkC0[0x14];
    unsigned int flags;

    static unsigned int s_Unk94F864;
};
