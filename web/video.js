// Draws VID1 messages (12-byte header + RGBA) onto the canvas; resizes when the game changes resolution.
export function createVideo(canvas) {
  const ctx = canvas.getContext("2d");
  let image = null;
  return {
    pixels() { return image; },  // last drawn frame (ImageData), for the overlay change check
    draw(buf) {
      const dv = new DataView(buf);
      const w = dv.getUint16(8, true), h = dv.getUint16(10, true);
      if (canvas.width !== w || canvas.height !== h || !image) {
        canvas.width = w; canvas.height = h;
        image = ctx.createImageData(w, h);
      }
      image.data.set(new Uint8ClampedArray(buf, 12, w * h * 4));
      ctx.putImageData(image, 0, 0);
      return dv.getUint32(4, true);
    },
  };
}
