#pragma once

#include <game/math/Vector.hpp>

struct FieldRect
{
    class iterator
    {
        public:
        iterator(const FieldRect* rect, const math::Vector2i* last, const math::Vector2i& position)
        {
            this->rect = rect;
            this->last = last;
            this->position = position;
        }

        iterator& operator++();

        bool operator==(const iterator& other) const
        {
            return IsValid() && other.IsValid() && other.position.x == position.x && other.position.y == position.y;
        }

        friend bool operator!=(const iterator& left, const iterator& right);

        private:
        friend struct FieldRect;

        bool IsValid() const { return rect && last; }

        void Advance()
        {
            if(!IsValid()) return;

            if(last->x <= position.x)
            {
                position.x = rect->min.x;
                ++position.y;
            }
            else
            {
                ++position.x;
            }
        }

        const FieldRect* rect;
        const math::Vector2i* last;
        math::Vector2i position;
    };

    iterator begin() const;
    iterator end() const;

    math::Vector2i min;
    math::Vector2i max;
};
