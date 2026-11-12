#include <nn/fnd/DateTime.hpp>

namespace nn { namespace fnd 
{
    int DateTime::DateToDays(int year, int month, int day)
    {
        day -= 1;
        year -= 2000;

        if(month <= 2)
        {
            month += 9;
            year -= 1;
        }
        else month -= 3;

        int leap = 1;
        if(year < 0) leap = IsLeapYear(year);

        return year / 100 * 146097 / 4 + year % 100 * 1461 / 4 + (153 * month + 2) / 5 + day + leap + 59;
    }

    void DateTime::DaysToDate(int* pYear, int* pMonth, int* pDay, int days)
    {
        days -= 60;

        int cycles400 = days / 146097;
        int rest400 = days % 146097;

        if(rest400 < 0)
        {
            --cycles400;
            rest400 += 146097;
        }

        int cycles100 = rest400 / 36524;
        int rest100 = rest400 % 36524;
        int cycles4 = rest100 / 1461;
        int rest4 = rest100 % 1461;
        int years = rest4 / 365;
        int dayOfYear = rest4 % 365;

        int month = (5 * dayOfYear + 2) / 153;
        int year = 2000 + 400 * cycles400 + 100 * cycles100 + 4 * cycles4 + years;
        int day = dayOfYear - (153 * month + 2) / 5 + 1;

        if(years == 4 || cycles100 == 4)
        {
            month = 11;
            day = 29;
            year -= 1;
        }

        if(month <= 9) month += 3;
        else
        {
            month -= 9;
            year += 1;
        }

        if(pYear) *pYear = year;
        if(pMonth) *pMonth = month;
        if(pDay) *pDay = day;
    }
}}
