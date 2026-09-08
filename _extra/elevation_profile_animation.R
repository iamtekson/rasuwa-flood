library(ggplot2)
library(gganimate)
library(geosphere)
library(gifski)

# =========================================================
# 1. READ DATA
# =========================================================

df <- read.csv(
  "C:\\Users\\Sagar\\Downloads\\flood_data.csv",
  header = TRUE,
  stringsAsFactors = FALSE,
  check.names = FALSE
)

# Ensure required columns are numeric
df$latitude <- as.numeric(df$latitude)
df$longitude <- as.numeric(df$longitude)
df$`altitude (m)` <- as.numeric(df$`altitude (m)`)


# =========================================================
# 2. CALCULATE CUMULATIVE DISTANCE
# =========================================================

df$segment_m <- c(
  0,
  geosphere::distHaversine(
    df[-nrow(df), c("longitude", "latitude")],
    df[-1, c("longitude", "latitude")]
  )
)

df$distance_km <- cumsum(df$segment_m) / 1000


# =========================================================
# 3. CREATE ANNOTATION DATAFRAME
# =========================================================

annotations <- df[
  !is.na(df$Annotate) &
    trimws(df$Annotate) != "",
]


# =========================================================
# 4. PAUSE TIME AT EACH ANNOTATION
#
# Value is number of REAL seconds to hold that frame.
#
# Example:
# 10 = pause for 10 seconds
#  5 = pause for 5 seconds
#  0 = no pause
# =========================================================



time_annotate <- c(
  0, 0, 10, 8, 10, 0, 10, 10, 10, 0, 0, 0, 0
)


# =========================================================
# 5. STOPWATCH TIME AT ANNOTATIONS
#
# NA means:
# no special clock calibration at that annotation.
#
# Stopwatch is interpolated between known times.
# After 09:38:00 it stops permanently.
# =========================================================

stop_watch_clock <- c(
  "08:41:00",
  "08:42:00",
  "08:44:00",
  "08:46:00",
  "08:50:00",
  NA,
  "09:24:00",
  "09:38:00",
  NA,
  NA,
  NA,
  NA,
  NA
)


# =========================================================
# 6. CHECK INPUT LENGTHS
# =========================================================

if (length(time_annotate) != nrow(annotations)) {
  stop(
    paste(
      "Number of annotations =", nrow(annotations),
      "but time_annotate has",
      length(time_annotate),
      "values."
    )
  )
}

if (length(stop_watch_clock) != nrow(annotations)) {
  stop(
    paste(
      "Number of annotations =", nrow(annotations),
      "but stop_watch_clock has",
      length(stop_watch_clock),
      "values."
    )
  )
}


# =========================================================
# 7. ANNOTATION VERTICAL OFFSETS
# =========================================================

elevation_annotate <- c(
  1000, 700, 500, 50, -250,
  2000, 1300, 200, -200, -100,
  800, 0, 0
)

if (nrow(annotations) != length(elevation_annotate)) {
  
  stop(
    paste(
      "Number of annotations =", nrow(annotations),
      "but elevation_annotate has",
      length(elevation_annotate),
      "values."
    )
  )
}


# =========================================================
# 8. PREPARE ANNOTATION POSITIONS
# =========================================================

annotations$trigger_x <- annotations$distance_km

annotations$anno_y <- annotations$`altitude (m)`

annotations$anno_yend <-
  annotations$`altitude (m)` +
  500 +
  elevation_annotate

annotations$text_y <-
  annotations$anno_yend + 30

annotations$label_text <- paste0(
  annotations$`Time(s)`,
  "\n",
  annotations$Annotate
)


# =========================================================
# 9. STATIC BACKGROUND PROFILE
# =========================================================

background <- data.frame(
  bg_distance = df$distance_km,
  bg_altitude = df$`altitude (m)`
)


# =========================================================
# 10. STOPWATCH FUNCTIONS
# =========================================================

# ---------------------------------------------------------
# HH:MM:SS -> seconds after midnight
# ---------------------------------------------------------

hms_to_seconds <- function(x) {
  
  if (is.na(x)) {
    return(NA_real_)
  }
  
  z <- strsplit(x, ":")[[1]]
  
  as.numeric(z[1]) * 3600 +
    as.numeric(z[2]) * 60 +
    as.numeric(z[3])
}


# ---------------------------------------------------------
# seconds after midnight -> HH:MM:SS
# ---------------------------------------------------------

seconds_to_hms <- function(x) {
  
  x <- round(x)
  
  hh <- floor(x / 3600)
  mm <- floor((x %% 3600) / 60)
  ss <- x %% 60
  
  sprintf(
    "%02d:%02d:%02d",
    hh,
    mm,
    ss
  )
}


# =========================================================
# 11. CREATE STOPWATCH CONTROL POINTS
# =========================================================

start_clock <- hms_to_seconds("08:33:00")

annotation_clock_sec <- sapply(
  stop_watch_clock,
  hms_to_seconds
)

valid_clock <- !is.na(annotation_clock_sec)


# Starting distance is normally exactly zero,
# but using min() makes this safer.

start_x <- min(
  df$distance_km,
  na.rm = TRUE
)


# Clock calibration positions

clock_x <- c(
  start_x,
  annotations$trigger_x[valid_clock]
)

clock_sec <- c(
  start_clock,
  annotation_clock_sec[valid_clock]
)


# Make sure clock anchors are ordered by distance

clock_order <- order(clock_x)

clock_x <- clock_x[clock_order]
clock_sec <- clock_sec[clock_order]


# Last known clock point
last_clock_x <- max(clock_x)

last_clock_sec <- clock_sec[
  which.max(clock_x)
]


# =========================================================
# 12. GET STOPWATCH TIME FOR ANY DISTANCE
# =========================================================

get_stopwatch_time <- function(x) {
  
  # After last known clock position:
  # permanently stop the stopwatch.
  
  if (x >= last_clock_x) {
    return(last_clock_sec)
  }
  
  
  # Interpolate stopwatch time between known locations.
  
  approx(
    x = clock_x,
    y = clock_sec,
    xout = x,
    method = "linear",
    rule = 2
  )$y
}


# =========================================================
# 13. ANIMATION SETTINGS
# =========================================================

fps <- 10

# Number of frames used for normal movement.
#
# Increase for smoother movement:
# 100 = quick preview
# 200-300 = smoother final animation

movement_frames <- 100


# =========================================================
# 14. CREATE NORMAL MOVEMENT DISTANCES
# =========================================================

normal_x <- seq(
  min(df$distance_km, na.rm = TRUE),
  max(df$distance_km, na.rm = TRUE),
  length.out = movement_frames
)


# =========================================================
# IMPORTANT:
# Force EVERY annotation location into the movement path.
#
# This guarantees that the red point lands EXACTLY on every
# annotation instead of jumping over it.
# =========================================================

movement_x <- sort(
  unique(
    c(
      normal_x,
      annotations$trigger_x
    )
  )
)


# =========================================================
# 15. BUILD FRAME TIMELINE
# =========================================================
#
# Every row = one rendered frame.
#
# Additional duplicate frames are inserted at annotation
# positions according to time_annotate.
#
# At 10 fps:
#
# 10 seconds = 100 duplicate frames
#  5 seconds =  50 duplicate frames
#  2 seconds =  20 duplicate frames
#
# =========================================================

timeline_list <- list()

frame_counter <- 0


for (i in seq_along(movement_x)) {
  
  current_x <- movement_x[i]
  
  
  # -------------------------------------------------------
  # NORMAL MOVEMENT FRAME
  # -------------------------------------------------------
  
  frame_counter <- frame_counter + 1
  
  timeline_list[[frame_counter]] <- data.frame(
    frame = frame_counter,
    current_x = current_x
  )
  
  
  # -------------------------------------------------------
  # IS CURRENT POSITION EXACTLY AN ANNOTATION?
  # -------------------------------------------------------
  
  annotation_index <- which(
    abs(annotations$trigger_x - current_x) < 1e-8
  )
  
  
  if (length(annotation_index) > 0) {
    
    for (j in annotation_index) {
      
      pause_seconds <- time_annotate[j]
      
      
      # ---------------------------------------------------
      # ADD EXTRA IDENTICAL FRAMES
      # ---------------------------------------------------
      
      if (
        !is.na(pause_seconds) &&
        pause_seconds > 0
      ) {
        
        pause_frames <- round(
          pause_seconds * fps
        )
        
        
        for (k in seq_len(pause_frames)) {
          
          frame_counter <- frame_counter + 1
          
          timeline_list[[frame_counter]] <- data.frame(
            frame = frame_counter,
            current_x = current_x
          )
        }
      }
    }
  }
}


timeline <- do.call(
  rbind,
  timeline_list
)


# =========================================================
# 16. CALCULATE STOPWATCH FOR EVERY FRAME
# =========================================================

timeline$clock_sec <- sapply(
  timeline$current_x,
  get_stopwatch_time
)

timeline$clock_label <- sapply(
  timeline$clock_sec,
  seconds_to_hms
)


# =========================================================
# 17. CREATE MOVING MARKER DATA
# =========================================================

marker_frames <- timeline


# Interpolate elevation at current marker position

marker_frames$altitude <- approx(
  x = df$distance_km,
  y = df$`altitude (m)`,
  xout = marker_frames$current_x,
  rule = 2
)$y


# =========================================================
# 18. CREATE REVEALED YELLOW PROFILE FOR EVERY FRAME
# =========================================================

profile_list <- vector(
  "list",
  nrow(timeline)
)


for (i in seq_len(nrow(timeline))) {
  
  x_now <- timeline$current_x[i]
  
  
  temp <- df[
    df$distance_km <= x_now,
  ]
  
  
  # -------------------------------------------------------
  # Add interpolated end point so the yellow line reaches
  # EXACTLY to the current red marker.
  # -------------------------------------------------------
  
  exact_match <- any(
    abs(df$distance_km - x_now) < 1e-8
  )
  
  
  if (!exact_match) {
    
    altitude_now <- approx(
      x = df$distance_km,
      y = df$`altitude (m)`,
      xout = x_now,
      rule = 2
    )$y
    
    
    extra_point <- df[1, ]
    
    extra_point[,] <- NA
    
    extra_point$distance_km <- x_now
    extra_point$`altitude (m)` <- altitude_now
    
    
    temp <- rbind(
      temp,
      extra_point
    )
  }
  
  
  temp$frame <- timeline$frame[i]
  
  profile_list[[i]] <- temp
}


profile_frames <- do.call(
  rbind,
  profile_list
)


# =========================================================
# 19. CREATE ACTIVE/HIGHLIGHTED ANNOTATIONS
# =========================================================
#
# Once the moving point reaches an annotation:
#
# grey segment -> green
# grey text    -> red
#
# The active color stays afterward.
# =========================================================

highlight_list <- vector(
  "list",
  nrow(timeline)
)


for (i in seq_len(nrow(timeline))) {
  
  x_now <- timeline$current_x[i]
  
  
  temp <- annotations[
    annotations$trigger_x <= x_now + 1e-8,
  ]
  
  
  if (nrow(temp) > 0) {
    
    temp$frame <- timeline$frame[i]
    
    highlight_list[[i]] <- temp
  }
}


highlight_frames <- do.call(
  rbind,
  highlight_list
)


# =========================================================
# 20. PRINT SOME INFORMATION
# =========================================================

cat("\n")
cat("Normal movement positions :", length(movement_x), "\n")
cat("Total rendered frames     :", nrow(timeline), "\n")
cat("FPS                       :", fps, "\n")
cat(
  "Approx. animation duration:",
  round(nrow(timeline) / fps, 1),
  "seconds\n"
)
cat("\n")

# =========================================================
# CREATE GREY "NOT YET REACHED" ANNOTATIONS
# =========================================================

pending_list <- vector(
  "list",
  nrow(timeline)
)

for (i in seq_len(nrow(timeline))) {
  
  x_now <- timeline$current_x[i]
  
  # Keep only annotations that marker has NOT reached yet
  temp <- annotations[
    annotations$trigger_x > x_now + 1e-8,
  ]
  
  if (nrow(temp) > 0) {
    
    temp$frame <- timeline$frame[i]
    
    pending_list[[i]] <- temp
  }
}

pending_frames <- do.call(
  rbind,
  pending_list
)
# =========================================================
# 21. CREATE PLOT
# =========================================================

p <- ggplot() +
  
  # =====================================================
# STATIC BACKGROUND
# =====================================================

geom_area(
  data = background,
  aes(
    x = bg_distance,
    y = bg_altitude
  ),
  stat = "identity",
  fill = "grey92",
  alpha = 1
) +
  
  geom_line(
    data = background,
    aes(
      x = bg_distance,
      y = bg_altitude
    ),
    color = "grey85",
    linewidth = 1.2
  ) +
  
  
  # =====================================================
# STATIC PRELOADED ANNOTATIONS
#
# All annotations are visible from frame 1.
# =====================================================

annotate(
  "segment",
  x = annotations$trigger_x,
  xend = annotations$trigger_x,
  y = annotations$anno_y,
  yend = annotations$anno_yend,
  colour = "grey75",
  linewidth = 0.8
) +
  
  geom_text(
    data = pending_frames,
    aes(
      x = trigger_x + 1,
      y = text_y,
      label = label_text,
      group = interaction(frame, trigger_x)
    ),
    colour = "grey50",
    size = 3,
    vjust = 0,
    hjust = 0,
    lineheight = 0.8,
    inherit.aes = FALSE
  ) +
  # =====================================================
# ANIMATED YELLOW FILLED PROFILE
# =====================================================

geom_area(
  data = profile_frames,
  aes(
    x = distance_km,
    y = `altitude (m)`,
    group = frame
  ),
  stat = "identity",
  fill = "#FFE4C4",
  alpha = 0.7
) +
  
  geom_line(
    data = profile_frames,
    aes(
      x = distance_km,
      y = `altitude (m)`,
      group = frame
    ),
    color = "#CD3333",
    linewidth = 1
  ) +
  
  
  # =====================================================
# ACTIVE ANNOTATIONS
#
# Overlay grey annotations after marker reaches them.
# =====================================================

geom_segment(
  data = highlight_frames,
  aes(
    x = trigger_x,
    xend = trigger_x,
    y = anno_y,
    yend = anno_yend,
    group = interaction(frame, trigger_x)
  ),
  colour = "green",
  linewidth = 0.8,
  inherit.aes = FALSE
) +
  
  geom_text(
    data = highlight_frames,
    aes(
      x = trigger_x + 1,
      y = text_y,
      label = label_text,
      group = interaction(frame, trigger_x)
    ),
    colour = "black",
    size = 5,
    fontface = "bold",
    vjust = 0,
    hjust = 0,
    lineheight = 0.8,
    inherit.aes = FALSE
  ) +
  
  
  # =====================================================
# MOVING RED POINT
# =====================================================

geom_point(
  data = marker_frames,
  aes(
    x = current_x,
    y = altitude,
    group = frame
  ),
  color = "#FF4040",
  size = 3.5
) +
  
  
  # =====================================================
# STATIC STOPWATCH TITLE
# =====================================================

# =====================================================
# ANIMATED STOPWATCH
# =====================================================

geom_text(
  data = timeline,
  aes(
    x = Inf,
    y = Inf,
    label = clock_label,
    group = frame
  ),
  hjust = 1.15,
  vjust = 1.4,
  size = 5.5,
  fontface = "bold",
  inherit.aes = FALSE
) +
  
  
  # =====================================================
# LABELS
# =====================================================

labs(
  title = "26 Aug 2026 | Nepal Flash Flood",
  x = "Distance (km)",
  y = "Elevation (m)"
) +
  
  
  # =====================================================
# STYLE
# =====================================================

theme_minimal() +
  
  
  # =====================================================
# FIXED AXIS LIMITS
#
# This prevents the layout from changing between frames.
# =====================================================

coord_cartesian(
  xlim = c(
    min(df$distance_km, na.rm = TRUE),
    max(df$distance_km, na.rm = TRUE) + 5
  ),
  ylim = c(
    min(df$`altitude (m)`, na.rm = TRUE),
    max(annotations$text_y, na.rm = TRUE) + 100
  ),
  clip = "off"
) +
  
  
  theme(
    plot.title = element_text(
      colour = "red",
      size=18
    ),
    plot.margin = margin(
      t = 20,
      r = 40,
      b = 10,
      l = 10
    )
  ) +
  
  
  # =====================================================
# EXPLICIT FRAME-BASED ANIMATION
# =====================================================

transition_manual(frame)

# =========================================================
# 22. RENDER PREVIEW
# =========================================================

anim <- animate(
  p,
  renderer = gifski_renderer(),
  width = 600,
  height = 400,
  nframes = nrow(timeline),
  fps = fps,
  res = 72
)

anim

# High-resolution GIF
anim_gif <- animate(
  p,
  renderer = gifski_renderer(),
  width = 1600,
  height = 1000,
  nframes = nrow(timeline),
  fps = fps,
  res = 150
)

anim_save(
  "C:\\Users\\Sagar\\Downloads\\elevation_profile.gif",
  animation = anim_gif
)


# Full-HD MP4
anim_mp4 <- animate(
  p,
  renderer = av_renderer(
    "C:\\Users\\Sagar\\Downloads\\elevation_profile.mp4"
  ),
  width = 1920,
  height = 1080,
  nframes = nrow(timeline),
  fps = fps,
  res = 150
)
