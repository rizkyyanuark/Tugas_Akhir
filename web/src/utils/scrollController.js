import { nextTick } from 'vue'

/**
 * Scroll Control Utility Class
 */
export class ScrollController {
  constructor(containerSelector = '.chat', options = {}) {
    this.containerSelector = containerSelector
    this.options = {
      threshold: 100,
      scrollDelay: 100,
      retryDelays: [50, 150],
      ...options
    }

    this.scrollTimer = null
    this.isUserScrolling = false
    this.shouldAutoScroll = true
    this.isProgrammaticScroll = false

    // Bind the context of 'this' for the event handler
    this.handleScroll = this.handleScroll.bind(this)
  }

  /**
   * Get the scroll container
   * @returns {Element|null}
   */
  getContainer() {
    return document.querySelector(this.containerSelector)
  }

  /**
   * Check if at the bottom
   * @returns {boolean}
   */
  isAtBottom() {
    const container = this.getContainer()
    if (!container) return false

    const { threshold } = this.options
    return container.scrollHeight - container.scrollTop - container.clientHeight <= threshold
  }

  /**
   * Handle scroll event
   */
  handleScroll() {
    if (this.scrollTimer) {
      clearTimeout(this.scrollTimer)
    }

    // If it is a programmatic scroll, ignore this event
    if (this.isProgrammaticScroll) {
      this.isProgrammaticScroll = false
      return
    }

    // Mark user is scrolling
    this.isUserScrolling = true

    // Check if at bottom
    this.shouldAutoScroll = this.isAtBottom()

    // Reset user scroll state after some time when scrolling ends
    this.scrollTimer = setTimeout(() => {
      this.isUserScrolling = false
    }, this.options.scrollDelay)
  }

  /**
   * Wait for DOM layout to stabilize
   * @returns {Promise<void>}
   */
  async waitForLayoutStable() {
    // Use requestAnimationFrame to ensure DOM rendering is complete
    await new Promise((resolve) => requestAnimationFrame(resolve))
    // Wait an extra short time to ensure CSS layout is complete
    await new Promise((resolve) => setTimeout(resolve, 50))
  }

  /**
   * Smart scroll to bottom
   * @param {boolean} force - Whether to force scroll
   */
  async scrollToBottom(force = false) {
    await nextTick()
    // Wait for DOM layout to stabilize
    await this.waitForLayoutStable()

    // Only execute if auto-scroll is enabled (unless forced)
    if (!force && !this.shouldAutoScroll) return

    const container = this.getContainer()
    if (!container) return

    // Mark as programmatic scroll
    this.isProgrammaticScroll = true

    // Record container height before scrolling
    const initialHeight = container.scrollHeight

    const scrollOptions = {
      top: container.scrollHeight,
      behavior: 'smooth'
    }

    // Scroll immediately
    container.scrollTo(scrollOptions)

    // Retry multiple times to ensure scroll success, including waiting for dynamic elements to finish layout
    const retryDelays = [50, 100, 200, 400]
    retryDelays.forEach((delay, index) => {
      setTimeout(() => {
        if (force || this.shouldAutoScroll) {
          this.isProgrammaticScroll = true
          const behavior = index === retryDelays.length - 1 ? 'auto' : 'smooth'

          // If height changed, dynamic content might be rendering, wait again
          if (container.scrollHeight !== initialHeight && index < retryDelays.length - 1) {
            this.waitForLayoutStable().then(() => {
              container.scrollTo({
                top: container.scrollHeight,
                behavior
              })
            })
          } else {
            container.scrollTo({
              top: container.scrollHeight,
              behavior
            })
          }
        }
      }, delay)
    })
  }

  async scrollToBottomStaticForce() {
    const container = this.getContainer()
    if (!container) return

    // Mark as programmatic scroll
    this.isProgrammaticScroll = true

    const scrollOptions = {
      top: container.scrollHeight,
      behavior: 'auto'
    }

    container.scrollTo(scrollOptions)
  }

  /**
   * Enable auto-scroll
   */
  enableAutoScroll() {
    this.shouldAutoScroll = true
  }

  /**
   * Disable auto-scroll
   */
  disableAutoScroll() {
    this.shouldAutoScroll = false
  }

  /**
   * Get scroll status
   */
  getScrollState() {
    return {
      isUserScrolling: this.isUserScrolling,
      shouldAutoScroll: this.shouldAutoScroll,
      isAtBottom: this.isAtBottom()
    }
  }

  /**
   * Cleanup timer
   */
  cleanup() {
    if (this.scrollTimer) {
      clearTimeout(this.scrollTimer)
      this.scrollTimer = null
    }
  }

  /**
   * Reset scroll status
   */
  reset() {
    this.cleanup()
    this.isUserScrolling = false
    this.shouldAutoScroll = true
    this.isProgrammaticScroll = false
  }
}

/**
 * Create a default scroll controller instance
 */
export const createScrollController = (containerSelector, options) => {
  return new ScrollController(containerSelector, options)
}

export default ScrollController
