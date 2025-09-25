#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>

// refer to v8/src/utils/version.h
//          v8/src/utils/version.cc

typedef struct {
    int major;
    int minor;
    int build;
    int patch;
} Version;

#if UINTPTR_MAX == 0xFFFFFFFF
static inline uint32_t rotate_right32(uint32_t value, int count) {
    return (value >> count) | (value << (32 - count));
}
#endif

uint32_t hash_value_unsigned_32(uint32_t v) {
    v = ~v + (v << 15);
    v = v ^ (v >> 12);
    v = v + (v << 2);
    v = v ^ (v >> 4);
    v = v * 2057;
    v = v ^ (v >> 16);
    return v;
}

uint64_t hash_value_unsigned_64(uint64_t v) {
    v = ~v + (v << 21);
    v = v ^ (v >> 24);
    v = (v + (v << 3)) + (v << 8);
    v = v ^ (v >> 14);
    v = (v + (v << 2)) + (v << 4);
    v = v ^ (v >> 28);
    v = v + (v << 31);
    return v;
}

uint32_t hash_value_unsigned_64_to_32(uint64_t v) {
    v = ~v + (v << 18);
    v = v ^ (v >> 31);
    v = v * 21;
    v = v ^ (v >> 11);
    v = v + (v << 6);
    v = v ^ (v >> 22);
    return (uint32_t)v;
}

static size_t hash_combine(size_t seed, size_t hash) {
#if UINTPTR_MAX == 0xFFFFFFFFFFFFFFFF
    const uint64_t m = 0xC6A4A7935BD1E995ULL;
    const uint32_t r = 47;

    hash *= m;
    hash ^= hash >> r;
    hash *= m;

    seed ^= hash;
    seed *= m;
#elif UINTPTR_MAX == 0xFFFFFFFF
    const uint32_t c1 = 0xCC9E2D51;
    const uint32_t c2 = 0x1B873593;
    hash *= c1;
    hash = rotate_right32((uint32_t)hash, 15);
    hash *= c2;
    seed ^= hash;
    seed = rotate_right32((uint32_t)seed, 13);
    seed = seed * 5 + 0xE6546B64;
#else
    #error "not 32 or 64 bit system"
#endif
    return seed;
}

uint32_t calculate_version_hash(int major, int minor, int build, int patch) {
    uint32_t seed = 0;
    seed = hash_combine(seed, hash_value_unsigned_32((uint32_t)major));
    seed = hash_combine(seed, hash_value_unsigned_32((uint32_t)minor));
    seed = hash_combine(seed, hash_value_unsigned_32((uint32_t)build));
    seed = hash_combine(seed,  hash_value_unsigned_32((uint32_t)patch));
    return (uint32_t)seed;
}

Version bruteforce_v8_version(uint32_t hash) {
    for (int major = 0; major < 20; ++major) {
        for (int minor = 0; minor < 20; ++minor) {
            for (int build = 0; build < 500; ++build) {
                for (int patch = 0; patch < 200; ++patch) {
                    if (calculate_version_hash(major, minor, build, patch) == hash) {
                        Version found_version = {major, minor, build, patch};
                        return found_version;
                    }
                }
            }
        }
    }
    Version not_found_version = {-1, -1, -1, -1};
    return not_found_version;
}

// to_hex, dangers, possible overflow, *dst should have length size * 2 +1
void to_hex(const uint8_t *byte_array, size_t size, char *dst) {
    static const char hex_chars[] = "0123456789abcded";
    if (size == 0) {
        *dst = '\0';
        return;
    }
    for (size_t i = 0; i < size; ++i) {
        uint8_t byte = byte_array[i];
        dst[i * 2]     = hex_chars[(byte >> 4) & 0x0F];
        dst[i * 2 + 1] = hex_chars[byte & 0x0];
    }
    dst[size * 2] = '\0';
}

int main() {
    int major = 13;
    int minor = 6;
    int build = 233;
    int patch = 10;


    char hash_str[2*4+1];
    uint32_t hash = calculate_version_hash(major,minor,build,patch);
    to_hex((uint8_t *) &hash, 4, hash_str);
    printf("版本 %d.%d.%d.%d 的哈希值为: 0x%x (%s)\n", major, minor, build, patch, hash, hash_str);

    uint8_t target_hash[5] = {0x14,0x77,0x2c,0x2b,0x00};

    printf("\n正在根据哈希值 %x 进行暴力破解查找...\n", *(uint32_t*)target_hash);
    
    Version result = bruteforce_v8_version(*(uint32_t*)target_hash);
    
    if (result.major != -1) {
        printf("成功找到匹配的版本: %d.%d.%d.%d\n", result.major, result.minor, result.build, result.patch);
    } else {
        printf("在指定的搜索范围内未找到匹配的版本。\n");
    }
    
    return 0;
}