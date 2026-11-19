#pragma once

#include <game/ssys/st/List.hpp>

namespace ssys { namespace ma { namespace lyt
{
    class Base2D;

    class LayoutList : public st::List
    {
        public:
        virtual ~LayoutList();

        void Insert(Base2D* layout);
    };
}}}
