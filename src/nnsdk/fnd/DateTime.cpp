#include <nn/fnd/DateTime.hpp>

namespace nn { namespace fnd 
{
    int DateTime::DateToDays(int year, int month, int day)
    {
        int dayIndex = day - 1;
        int m;
        year -= 2000;

        if(month <= 2)
        {
            m = month + 9;
            year -= 1;
        }
        else m = month - 3;

        int leap = 3;
        if(year < 0) 
        {
            if (year % 400 == 0)
                leap = 1;
            else if (year % 100 == 0)
                leap = 0;
            else
                leap = ((year & 3) == 0);
        }
        
        return year / 100 * 146097 / 4 + year % 100 * 1461 / 4 + (153 * m + 2) / 5 + dayIndex + leap + 59;
    }
}}