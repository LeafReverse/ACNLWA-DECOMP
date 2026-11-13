#pragma once

namespace sead
{
    template<typename T>
    class SafeStringBase
    {
        public:
        static const T cNullChar;
        static const int MAXIMUM_LENGTH = 0x80000;

        SafeStringBase() : stringTop(&cNullChar) {}
        SafeStringBase(const T* str) : stringTop(str) {}
        virtual ~SafeStringBase() {}

        const T* cstr() const
        {
            assureTerminationImpl_();
            return stringTop;
        }

        int calcLength() const
        {
            assureTerminationImpl_();
            int length = 0;

            for(;;)
            {
                if(length > MAXIMUM_LENGTH || stringTop[length] == cNullChar) break;

                ++length;
            }

            if(length > MAXIMUM_LENGTH) return 0;

            return length;
        }

        protected:
        virtual void assureTerminationImpl_() const {}

        const T* stringTop;
    };

    template<typename T>
    class BufferedSafeStringBase : public SafeStringBase<T>
    {
        public:
        BufferedSafeStringBase(T* buffer, int size) : SafeStringBase<T>(buffer)
        {
            bufferSize = size;

            if(size > 0)
            {
                BufferedSafeStringBase<T>::assureTerminationImpl_();
                return;
            }

            this->stringTop = 0;
            bufferSize = 0;
        }

        virtual ~BufferedSafeStringBase() {}

        int getBufferSize() const { return bufferSize; }

        void clear() { getMutableStringTop_()[0] = this->cNullChar; }

        template<typename OtherType>
        int convertFromOtherType_(const SafeStringBase<OtherType>& src)
        {
            int copySize = src.calcLength();

            if(getBufferSize() <= copySize) copySize = getBufferSize() - 1;

            T* dst = getMutableStringTop_();
            const OtherType* srcStr = src.cstr();

            for(int i = 0; i < copySize; ++i) dst[i] = static_cast<T>(srcStr[i]);

            dst[copySize] = this->cNullChar;

            return copySize;
        }

        int convertFromWideCharString(const SafeStringBase<wchar_t>& str) { return convertFromOtherType_(str); }

        protected:
        virtual void assureTerminationImpl_() const
        {
            T* top = const_cast<T*>(this->stringTop);
            top[bufferSize - 1] = this->cNullChar;
        }

        T* getMutableStringTop_() { return const_cast<T*>(this->stringTop); }

        int bufferSize;
    };

    template<typename T, int N>
    class FixedSafeStringBase : public BufferedSafeStringBase<T>
    {
        public:
        FixedSafeStringBase() : BufferedSafeStringBase<T>(buffer, N) { this->clear(); }
        virtual ~FixedSafeStringBase() {}

        protected:
        T buffer[N];
    };

    template<int N>
    class FixedSafeString : public FixedSafeStringBase<char, N>
    {
        public:
        FixedSafeString() : FixedSafeStringBase<char, N>() {}
        virtual ~FixedSafeString() {}
    };
}
