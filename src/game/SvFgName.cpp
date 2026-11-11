#include <game/SvFgName.hpp>

#pragma arm
SvFgName::SvFgName() : id(ID_EMPTY), flags(0) {}

SvFgName& SvFgName::operator=(const SvFgName& other)
{
    id = other.id;
    flags = other.flags;
    return *this;
}

SvFgName::SvFgName(const SvFgName& other) : id(other.id), flags(other.flags) {}

bool SvFgName::IsEmpty() const
{
    return GetId() == ID_EMPTY;
}

bool SvFgName::IsUsual() const
{
    return static_cast<unsigned int>(GetId() - ID_USUAL_FIRST) < ID_USUAL_COUNT;
}

item::Kind SvFgName::GetKind() const
{
    const UsualParam* param = GetUsualParam();
    if(!param) return item::KIND_END;

    return param->kind < item::KIND_END ? static_cast<item::Kind>(param->kind) : item::KIND_DEFAULT;
}

bool operator==(const SvFgName& left, SvFgName::ID right)
{
    return left.GetId() == right;
}

bool SvFgName::IsBuried() const
{
    return flags >> FLAG_BURIED_SHIFT;
}

SvFgName::SvFgName(ID fgId)
{
    unsigned short maskedId = fgId & ID_MASK;
    flags = 0;
    id = maskedId;
    unsigned int category = GetCategory();
    if(category < INIT_CATEGORY_COUNT)
    {
        const InitFunc* init = &initTable[category];
        (this->*(*init))();
    }
}

bool SvFgName::IsFg() const
{
    return GetId() <= ID_FG_LAST;
}

unsigned char SvFgName::GetFgKind() const
{
    if(IsFg())
    {
        const FgParam* param = GetFgParam();
        if(!param) return 0;

        return param->kind < FG_KIND_COUNT ? param->kind : 0;
    }

    return FG_KIND_COUNT;
}
