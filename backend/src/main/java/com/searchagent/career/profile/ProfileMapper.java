package com.searchagent.career.profile;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
interface ProfileMapper {
    @Select("SELECT target_role, graduation_month, preferences FROM career_profile WHERE user_id = #{userId}")
    ProfileService.Profile find(String userId);

    @Insert("""
            INSERT INTO career_profile (user_id, target_role, graduation_month, preferences)
            VALUES (#{userId}, #{profile.targetRole}, #{profile.graduationMonth}, #{profile.preferences}) AS incoming
            ON DUPLICATE KEY UPDATE target_role = incoming.target_role,
                graduation_month = incoming.graduation_month, preferences = incoming.preferences
            """)
    void save(@Param("userId") String userId, @Param("profile") ProfileService.Profile profile);
}
