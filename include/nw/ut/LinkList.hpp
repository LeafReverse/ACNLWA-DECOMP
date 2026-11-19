#pragma once

namespace nw { namespace ut 
{
    struct LinkListNode
    {
        LinkListNode* next;
        LinkListNode* prev;
    };

    namespace internal
    {
        class LinkListImpl
        {
            public:
            class ConstIterator
            {
                public:
                explicit ConstIterator(const LinkListNode* node) : node(node) {}

                const LinkListNode* operator->() const 
                { 
                    return node; 
                }

                const LinkListNode& operator*() const 
                {
                    return *node;
                }

                ConstIterator& operator++() 
                { 
                    node = node->next; 
                    return *this; 
                }

                bool operator==(const ConstIterator& other) const 
                { 
                    return node == other.node; 
                }

                bool operator!=(const ConstIterator& other) const 
                { 
                    return node != other.node; 
                }

                private:
                const LinkListNode* node;
            };

            ConstIterator GetBeginIter() const 
            { 
                return ConstIterator(root.next); 
            }
           
            ConstIterator GetEndIter() const 
            { 
                return ConstIterator(&root); 
            }

            LinkListNode* erase(LinkListNode* node);

            private:
            unsigned int count;
            LinkListNode root;
        };
    }

    typedef internal::LinkListImpl LinkList;
}}
