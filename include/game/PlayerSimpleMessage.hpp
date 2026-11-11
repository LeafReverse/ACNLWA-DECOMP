#pragma once

#include <nn/fnd/DateTime.hpp>

class PlayerSimpleMessage
{
    // They are found in the middle of vfunc of PlayerSimpleMessage, IMO
    // it should not be in there, but theoretically it's in this class 
    // i want to fucked the ARMCC compiler stuff are so strange fr
    
    public:
    static nn::fnd::DateTimeParameters* GetDateTime();

    private:
    static nn::fnd::DateTimeParameters dateTime;
};
