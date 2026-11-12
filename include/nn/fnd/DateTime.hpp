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
        static bool IsLeapYear(int year)
        {
            if(year % 400 == 0) return true;
            if(year % 100 == 0) return false;
            if(year % 4 == 0) return true;

            return false;
        }

        static int DateToDays(int year, int month, int day);
        static void DaysToDate(int* pYear, int* pMonth, int* pDay, int days);
    };
}}
