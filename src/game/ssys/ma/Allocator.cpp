#include <game/ssys/ma/Allocator.hpp>

#pragma arm
ssys::ma::Allocator::Allocator() : heap(0) {}

ssys::ma::Allocator::~Allocator() {}

bool ssys::ma::Allocator::SetHeap(sead::Heap* newHeap)
{
    heap = newHeap;
    return true;
}

void* ssys::ma::Allocator::Alloc(unsigned int size, int alignment)
{
    if(alignment == 0) alignment = 1;

    return heap->tryAlloc(size + alignment, alignment);
}

void ssys::ma::Allocator::Free(void* memory)
{
    heap->free(memory);
}
