export function currentProfileRating(profile) {
  return profile?.current_skill_level || profile?.skill_level || ''
}

export function initialProfileRating(profile) {
  return profile?.initial_skill_level || profile?.skill_level || ''
}

export function matchesProfileRating(profile, rating) {
  const current = currentProfileRating(profile)
  return !rating || (current === '进阶' ? '高级' : current) === rating
}
