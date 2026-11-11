#pragma once

namespace nw { namespace ut 
{
    namespace internal
    {
        struct RuntimeTypeInfo
        {
            const RuntimeTypeInfo* parent;

            bool IsDerivedFrom(const RuntimeTypeInfo* other) const
            {
                const RuntimeTypeInfo* self = this;
                while(self)
                {
                    if(self == other) return true;

                    self = self->parent;
                }

                return false;
            }
        };
    }

    template <typename TTo, typename TFrom> TTo* DynamicCast(TFrom* object)
    {
        const internal::RuntimeTypeInfo* target = &TTo::typeInfo;
        if(object && object->GetRuntimeTypeInfo()->IsDerivedFrom(target)) return static_cast<TTo*>(object);

        return 0;
    }
}}
