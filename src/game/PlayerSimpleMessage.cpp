#include <game/PlayerSimpleMessage.hpp>

#pragma arm
nn::fnd::DateTimeParameters* PlayerSimpleMessage::GetDateTime()
{
    return &dateTime;
}
