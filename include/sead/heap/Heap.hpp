#pragma once

namespace sead
{
    class Heap
    {
        public:
        virtual ~Heap();
        virtual bool checkDerivedRuntimeTypeInfo(const void* typeInfo) const;
        virtual const void* getRuntimeTypeInfo() const;
        virtual void destroy() = 0;
        virtual unsigned int adjust() = 0;
        virtual void* tryAlloc(unsigned int size, int alignment) = 0;
        virtual void free(void* ptr) = 0;
    };
}
