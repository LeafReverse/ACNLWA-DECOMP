#pragma once

#include <sead/heap/Heap.hpp>

namespace ssys { namespace ma
{
    class Allocator
    {
        public:
        Allocator();
        virtual ~Allocator();
        virtual void* Alloc(unsigned int size, int alignment);
        virtual void Free(void* memory);

        bool SetHeap(sead::Heap* newHeap);
        sead::Heap* GetHeap() const { return heap; }

        private:
        sead::Heap* heap;
    };
}}
