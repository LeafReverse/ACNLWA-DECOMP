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
        if(!object) return 0;

        return object->GetRuntimeTypeInfo()->IsDerivedFrom(target) ? static_cast<TTo*>(object) : 0;
    }
}}
