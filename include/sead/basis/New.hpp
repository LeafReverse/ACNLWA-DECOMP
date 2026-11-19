#pragma once

namespace sead
{
    class Heap;
}

void* operator new[](unsigned int size, sead::Heap* heap, int alignment);
