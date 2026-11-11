// The Android NVN replay's Vulkan device (gfx_vk.c), shared with the front end that presents the game's window texture (front_android.c).
#pragma once
#include <pthread.h>
#include <stdint.h>
#define VK_USE_PLATFORM_ANDROID_KHR 1
#define VK_NO_PROTOTYPES 1   // every vk* below is a pointer, filled from the driver vk_driver.c opens: the system's, or DM_VK_DRIVER's
#include <vulkan/vulkan.h>

// The Vulkan functions the replay and the front end call. GLOBAL: loaded before there is an instance; the others through it (vk_driver_instance)
#define VKB_FNS_GLOBAL(X) X(vkCreateInstance) X(vkEnumerateInstanceExtensionProperties)
#define VKB_FNS(X) \
    X(vkAcquireNextImageKHR) X(vkAllocateCommandBuffers) X(vkAllocateDescriptorSets) X(vkAllocateMemory) X(vkBeginCommandBuffer) X(vkBindBufferMemory) \
    X(vkBindImageMemory) X(vkCmdBeginQuery) X(vkCmdBeginRenderPass) X(vkCmdBindDescriptorSets) X(vkCmdBindIndexBuffer) X(vkCmdBindPipeline) \
    X(vkCmdBindVertexBuffers) X(vkCmdBlitImage) X(vkCmdClearAttachments) X(vkCmdClearColorImage) X(vkCmdClearDepthStencilImage) X(vkCmdCopyBuffer) X(vkCmdCopyBufferToImage) \
    X(vkCmdCopyImage) X(vkCmdCopyImageToBuffer) X(vkCmdDispatch) X(vkCmdDraw) X(vkCmdDrawIndexed) X(vkCmdEndQuery) X(vkCmdEndRenderPass) \
    X(vkCmdPipelineBarrier) X(vkCmdPushConstants) X(vkCmdResetQueryPool) X(vkCmdResolveImage) X(vkCmdSetBlendConstants) X(vkCmdSetDepthBias) \
    X(vkCmdSetScissor) X(vkCmdSetStencilCompareMask) X(vkCmdSetStencilReference) X(vkCmdSetStencilWriteMask) X(vkCmdSetViewport) X(vkCmdWriteTimestamp) \
    X(vkCreateAndroidSurfaceKHR) X(vkCreateBuffer) X(vkCreateBufferView) X(vkCreateCommandPool) X(vkCreateComputePipelines) X(vkCreateDescriptorPool) \
    X(vkCreateDescriptorSetLayout) X(vkCreateDevice) X(vkCreateFence) X(vkCreateFramebuffer) X(vkCreateGraphicsPipelines) X(vkCreateImage) \
    X(vkCreateImageView) X(vkCreatePipelineCache) X(vkCreatePipelineLayout) X(vkCreateQueryPool) X(vkCreateRenderPass) X(vkCreateSampler) \
    X(vkCreateSemaphore) X(vkCreateShaderModule) X(vkCreateSwapchainKHR) X(vkDestroyBuffer) X(vkDestroyBufferView) X(vkDestroyFramebuffer) \
    X(vkDestroyImage) X(vkDestroyImageView) X(vkDestroyPipeline) X(vkDestroyPipelineLayout) X(vkDestroyShaderModule) X(vkDestroySurfaceKHR) X(vkDestroySwapchainKHR) \
    X(vkDeviceWaitIdle) X(vkEndCommandBuffer) X(vkEnumerateDeviceExtensionProperties) X(vkEnumeratePhysicalDevices) X(vkFlushMappedMemoryRanges) X(vkFreeMemory) \
    X(vkGetBufferMemoryRequirements) X(vkGetDeviceProcAddr) X(vkGetDeviceQueue) X(vkGetImageMemoryRequirements) X(vkGetPhysicalDeviceFeatures) \
    X(vkGetPhysicalDeviceFeatures2) X(vkGetPhysicalDeviceFormatProperties) X(vkGetPhysicalDeviceImageFormatProperties) X(vkGetPhysicalDeviceMemoryProperties) X(vkGetPhysicalDeviceProperties) \
    X(vkGetPhysicalDeviceProperties2) X(vkGetPhysicalDeviceQueueFamilyProperties) X(vkGetPhysicalDeviceSurfaceCapabilitiesKHR) X(vkGetPhysicalDeviceSurfaceFormatsKHR) \
    X(vkGetPhysicalDeviceSurfaceSupportKHR) X(vkGetPipelineCacheData) X(vkGetQueryPoolResults) X(vkGetSwapchainImagesKHR) X(vkInvalidateMappedMemoryRanges) X(vkMapMemory) X(vkQueuePresentKHR) \
    X(vkQueueSubmit) X(vkResetCommandBuffer) X(vkResetCommandPool) X(vkResetDescriptorPool) X(vkResetFences) X(vkUnmapMemory) X(vkUpdateDescriptorSets) \
    X(vkWaitForFences)
#define VKB_DECL(f) extern __attribute__((visibility("hidden"))) PFN_##f f;
VKB_FNS_GLOBAL(VKB_DECL) VKB_FNS(VKB_DECL)
#undef VKB_DECL
// vk_driver.c. vk_driver_dirs (the front end, before the device is made): DM_VK_DRIVER is looked for relative to ext, the folder env.txt is in, and copied into internal.
// vk_driver_load: the driver opened and the GLOBAL functions loaded (0: no Vulkan); vk_driver_instance: the others, once the instance is made.
// vk_driver_name: the DM_VK_DRIVER file running (its name), NULL on the system's driver
void vk_driver_dirs(const char *ext, const char *internal);
int vk_driver_load(void);
void vk_driver_instance(VkInstance inst);
const char *vk_driver_name(void);

typedef struct {
    VkInstance inst; VkPhysicalDevice pd; VkDevice dev; VkQueue q; uint32_t qf;
    VkPhysicalDeviceProperties props; VkPhysicalDeviceMemoryProperties mp;
    int has_bc, has_astc, has_surface, has_swapchain;
    int has_display_timing;   // VK_GOOGLE_display_timing enabled: frames start on the display's vsyncs and are shown at a given time (gfx_vk_vsync.inc)
    pthread_mutex_t qmu;   // every vkQueueSubmit / vkQueuePresentKHR / vkQueueWaitIdle on q
} vkb_ctx;
vkb_ctx *vkb(void);        // made at first use; NULL when the device has no usable Vulkan

// The window texture the game presented last (NVN QueuePresentTexture), for the front end to draw: always in VK_IMAGE_LAYOUT_GENERAL.
// vkb_frame_lock holds it (the texture is not destroyed meanwhile) until vkb_frame_unlock; 0 = no frame yet
typedef struct { VkImage img; VkFormat fmt; uint32_t w, h; int crop[4]; uint64_t n; int flip; uint64_t show_at; } vkb_frame;   // flip: stored bottom-up (NVN's lower-left window origin), shown flipped;
                                                                                                                      // show_at: when to show it (CLOCK_MONOTONIC ns, 0 = as soon as drawn; gfx_vk_vsync.inc)
int vkb_frame_lock(vkb_frame *f);
void vkb_pipeline_cache_save(void);   // the driver's compiled pipelines to DM_PIPELINE_CACHE, when they grew (the app paused or stopped)
void vkb_frame_unlock(void);
uint32_t vkb_mem_type(uint32_t bits, VkMemoryPropertyFlags want);   // a memory type index of bits with the wanted properties (UINT32_MAX = none)
