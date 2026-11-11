#pragma once

class ButtonActionNode
{
    public:
    virtual ~ButtonActionNode();

    int GetIndex() const { return index; }

    private:
    unsigned char unk4[0xC4];
    int index;
};
