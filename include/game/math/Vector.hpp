#pragma once

namespace math
{
    template <typename T, unsigned int N> struct Vector;

    template <typename T> struct Vector<T, 2>
    {
        T x;
        T y;

        Vector() : x(0), y(0) {}

        Vector& operator=(const Vector& other)
        {
            x = other.x;
            y = other.y;
            return *this;
        }
    };

    typedef Vector<int, 2> Vector2i;
}
