#pragma once

#include <game/item/Kind.hpp>

class SvFgName
{
    public:
    enum ID
    {
        ID_EMPTY = 0x7FFE
    };

    enum
    {
        ID_MASK = 0x7FFF,
        ID_CATEGORY_SHIFT = 13,
        ID_CATEGORY_MASK = 3,
        ID_FG_LAST = 0xFD,
        ID_USUAL_FIRST = 0x2000,
        ID_USUAL_COUNT = 0x172B,
        FLAG_BURIED_SHIFT = 15,
        FG_KIND_COUNT = 29,
        INIT_CATEGORY_COUNT = 2
    };

    struct UsualParam
    {
        unsigned char unk0[10];
        unsigned char kind;
    };

    struct FgParam
    {
        unsigned char unk0[10];
        unsigned char kind;
    };

    SvFgName();
    SvFgName(ID fgId);
    SvFgName(const SvFgName& other);
    SvFgName& operator=(const SvFgName& other);

    friend bool operator==(const SvFgName& left, ID right);

    unsigned short GetId() const { return id & ID_MASK; }
    unsigned int GetCategory() const { return (GetId() >> ID_CATEGORY_SHIFT) & ID_CATEGORY_MASK; }
    bool IsEmpty() const;
    bool IsUsual() const;
    bool IsFg() const;
    bool IsBuried() const;
    item::Kind GetKind() const;
    unsigned char GetFgKind() const;

    private:
    typedef void (SvFgName::*InitFunc)();

    const UsualParam* GetUsualParam() const;
    const FgParam* GetFgParam() const;

    static const InitFunc initTable[INIT_CATEGORY_COUNT];

    unsigned short id;
    unsigned short flags;
};
