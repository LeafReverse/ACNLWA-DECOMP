#include <game/field/FieldRect.hpp>

#pragma arm
FieldRect::iterator& FieldRect::iterator::operator++()
{
    Advance();
    return *this;
}

bool operator!=(const FieldRect::iterator& left, const FieldRect::iterator& right)
{
    return !(left == right);
}

FieldRect::iterator FieldRect::end() const
{
    iterator it(this, &max, max);

    it.Advance();
    return it;
}

FieldRect::iterator FieldRect::begin() const
{
    return iterator(this, &max, min);
}
