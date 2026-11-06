package com.searchagent.career.profile;

import java.util.List;

import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
interface ExperienceMapper {
    String COLUMNS = "id, type, title, organization, start_month, end_month, description, source_note, confirmed";

    @Select("SELECT " + COLUMNS + " FROM career_experience WHERE user_id = #{userId} ORDER BY created_at DESC, id DESC")
    List<ExperienceService.Entry> list(String userId);

    @Select("SELECT " + COLUMNS + " FROM career_experience WHERE user_id = #{userId} AND id = #{id}")
    ExperienceService.Entry find(@Param("userId") String userId, @Param("id") String id);

    @Insert("""
            INSERT INTO career_experience (user_id, id, type, title, organization, start_month, end_month, description, source_note, confirmed)
            VALUES (#{userId}, #{id},
                #{entry.type}, #{entry.title}, #{entry.organization}, #{entry.startMonth}, #{entry.endMonth}, #{entry.description}, #{entry.sourceNote}, #{entry.confirmed})
            """)
    void insert(@Param("userId") String userId, @Param("id") String id, @Param("entry") ExperienceService.Input entry);

    @Update("""
            UPDATE career_experience
            SET type = #{entry.type}, title = #{entry.title}, organization = #{entry.organization},
                start_month = #{entry.startMonth}, end_month = #{entry.endMonth}, description = #{entry.description},
                source_note = #{entry.sourceNote}, confirmed = #{entry.confirmed}
            WHERE user_id = #{userId} AND id = #{id}
            """)
    void update(@Param("userId") String userId, @Param("id") String id, @Param("entry") ExperienceService.Input entry);

    @Delete("DELETE FROM career_experience WHERE user_id = #{userId} AND id = #{id}")
    int delete(@Param("userId") String userId, @Param("id") String id);
}
