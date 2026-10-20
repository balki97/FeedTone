#if defined(_WIN32)
#define FT_EXPORT __declspec(dllexport)
#else
#define FT_EXPORT __attribute__((visibility("default")))
#endif
#if !defined(__x86_64__) && !defined(_M_X64)
#include <math.h>
#endif
