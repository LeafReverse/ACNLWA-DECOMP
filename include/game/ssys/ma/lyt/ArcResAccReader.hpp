#pragma once

#include <game/ssys/ma/LoadSplit.hpp>
#include <game/ssys/ma/lyt/ArcResAcc.hpp>

namespace ssys { namespace ma { namespace lyt
{
    class ArcResAccReader : public ArcResAcc
    {
        public:
        ArcResAccReader();
        virtual ~ArcResAccReader();

        bool ReadArc(const char* name);
        bool ReadArc(const char* name, unsigned long alignment, unsigned long splitSize);
        bool ReadArc(const char* name, sead::Heap* heap);
        bool ReadArc(const char* name, sead::Heap* heap, unsigned long alignment, unsigned long splitSize);
        bool ReadArcAll(const char* name);
        bool ReadArcAll(const char* name, unsigned long alignment);

        private:
        struct Statics
        {
            unsigned char unk0;
            unsigned long alignment;
            unsigned long splitSize;
        };

        static Statics s_Statics;

        void* arcData;
        LoadSplit loader;
    };
}}}
