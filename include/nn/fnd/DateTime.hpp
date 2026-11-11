#pragma once

namespace nn { namespace fnd 
{
    struct DateTimeParameters
    {
        int year;
        signed char month;
        signed char day;
        signed char week;
        signed char hour;
        signed char minute;
        signed char second;
        short milliSecond;
    };

    class DateTime 
    {
        public:
        static int DateToDays(int year, int month, int day);
    };
}}
