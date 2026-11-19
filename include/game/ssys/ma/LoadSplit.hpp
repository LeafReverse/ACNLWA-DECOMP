#pragma once

#include <sead/heap/Heap.hpp>
#include <sead/prim/SafeString.hpp>

namespace ssys { namespace ma
{
    class LoadSplit
    {
        public:
        virtual ~LoadSplit();

        bool Read(const sead::SafeStringBase<char>& path, sead::Heap* heap, unsigned long alignment, unsigned long splitSize);
        bool ReadAll(const sead::SafeStringBase<char>& path, sead::Heap* heap, unsigned long alignment);

        void* GetData() const { return data; }

        private:
        unsigned char unk4[0xCC];
        void* data;
    };
}}
